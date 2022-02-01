"""
Tests for elementwise functions

https://data-apis.github.io/array-api/latest/API_specification/elementwise_functions.html

This tests behavior that is explicitly mentioned in the spec. Note that the
spec does not make any accuracy requirements for functions, so this does not
test that. Tests for the special cases are generated and tested separately in
special_cases/
"""

import math
import operator
from enum import Enum, auto
from typing import Callable, List, NamedTuple, Optional, Union

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from hypothesis.control import reject

from . import _array_module as xp
from . import array_helpers as ah
from . import dtype_helpers as dh
from . import hypothesis_helpers as hh
from . import pytest_helpers as ph
from . import shape_helpers as sh
from . import xps
from .typing import Array, DataType, Param, Scalar, ScalarType, Shape

pytestmark = pytest.mark.ci


def all_integer_dtypes() -> st.SearchStrategy[DataType]:
    """Returns a strategy for signed and unsigned integer dtype objects."""
    return xps.unsigned_integer_dtypes() | xps.integer_dtypes()


def boolean_and_all_integer_dtypes() -> st.SearchStrategy[DataType]:
    """Returns a strategy for boolean and all integer dtype objects."""
    return xps.boolean_dtypes() | all_integer_dtypes()


def isclose(a: float, b: float, rel_tol: float = 0.25, abs_tol: float = 1) -> bool:
    """Wraps math.isclose with more generous defaults."""
    if not (math.isfinite(a) and math.isfinite(b)):
        raise ValueError(f"{a=} and {b=}, but input must be finite")
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def mock_int_dtype(n: int, dtype: DataType) -> int:
    """Returns equivalent of `n` that mocks `dtype` behaviour"""
    nbits = dh.dtype_nbits[dtype]
    mask = (1 << nbits) - 1
    n &= mask
    if dh.dtype_signed[dtype]:
        highest_bit = 1 << (nbits - 1)
        if n & highest_bit:
            n = -((~n & mask) + 1)
    return n


def unary_assert_against_refimpl(
    func_name: str,
    in_: Array,
    res: Array,
    refimpl: Callable[[Scalar], Scalar],
    expr_template: str,
    in_stype: Optional[ScalarType] = None,
    res_stype: Optional[ScalarType] = None,
    filter_: Callable[[Scalar], bool] = math.isfinite,
):
    if in_.shape != res.shape:
        raise ValueError(f"{res.shape=}, but should be {in_.shape=}")
    if in_stype is None:
        in_stype = dh.get_scalar_type(in_.dtype)
    if res_stype is None:
        res_stype = in_stype
    for idx in sh.ndindex(in_.shape):
        scalar_i = in_stype(in_[idx])
        if not filter_(scalar_i):
            continue
        expected = refimpl(scalar_i)
        scalar_o = res_stype(res[idx])
        f_i = sh.fmt_idx("x", idx)
        f_o = sh.fmt_idx("out", idx)
        expr = expr_template.format(f_i, expected)
        assert scalar_o == expected, (
            f"{f_o}={scalar_o}, but should be {expr} [{func_name}()]\n"
            f"{f_i}={scalar_i}"
        )


def binary_assert_against_refimpl(
    func_name: str,
    left: Array,
    right: Union[Scalar, Array],
    res: Array,
    refimpl: Callable[[Scalar, Scalar], Scalar],
    expr_template: str,
    in_stype: Optional[ScalarType] = None,
    res_stype: Optional[ScalarType] = None,
    left_sym: str = "x1",
    right_sym: str = "x2",
    res_name: str = "out",
    filter_: Callable[[Scalar], bool] = math.isfinite,
):
    if in_stype is None:
        in_stype = dh.get_scalar_type(left.dtype)
    if res_stype is None:
        res_stype = in_stype
    result_dtype = dh.result_type(left.dtype, right.dtype)
    if result_dtype != xp.bool:
        m, M = dh.dtype_ranges[result_dtype]
    for l_idx, r_idx, o_idx in sh.iter_indices(left.shape, right.shape, res.shape):
        scalar_l = in_stype(left[l_idx])
        scalar_r = in_stype(right[r_idx])
        if not (filter_(scalar_l) and filter_(scalar_r)):
            continue
        expected = refimpl(scalar_l, scalar_r)
        if result_dtype != xp.bool:
            if expected <= m or expected >= M:
                continue
        scalar_o = res_stype(res[o_idx])
        f_l = sh.fmt_idx(left_sym, l_idx)
        f_r = sh.fmt_idx(right_sym, r_idx)
        f_o = sh.fmt_idx(res_name, o_idx)
        expr = expr_template.format(f_l, f_r, expected)
        if dh.is_float_dtype(result_dtype):
            assert isclose(scalar_o, expected), (
                f"{f_o}={scalar_o}, but should be roughly {expr} [{func_name}()]\n"
                f"{f_l}={scalar_l}, {f_r}={scalar_r}"
            )
        else:
            assert scalar_o == expected, (
                f"{f_o}={scalar_o}, but should be {expr} [{func_name}()]\n"
                f"{f_l}={scalar_l}, {f_r}={scalar_r}"
            )


# When appropiate, this module tests operators alongside their respective
# elementwise methods. We do this by parametrizing a generalised test method
# with every relevant method and operator.
#
# Notable arguments in the parameter:
# - The function object, which for operator test cases is a wrapper that allows
#   test logic to be generalised.
# - The argument strategies, which can be used to draw arguments for the test
#   case. They may require additional filtering for certain test cases.
# - right_is_scalar (binary parameters), which denotes if the right argument is
#   a scalar in a test case. This can be used to appropiately adjust draw
#   filtering and test logic.


func_to_op = {v: k for k, v in dh.op_to_func.items()}
all_op_to_symbol = {**dh.binary_op_to_symbol, **dh.inplace_op_to_symbol}
finite_kw = {"allow_nan": False, "allow_infinity": False}


class UnaryParamContext(NamedTuple):
    func_name: str
    func: Callable[[Array], Array]
    strat: st.SearchStrategy[Array]

    @property
    def id(self) -> str:
        return f"{self.func_name}"

    def __repr__(self):
        return f"UnaryParamContext(<{self.id}>)"


def make_unary_params(
    elwise_func_name: str, dtypes_strat: st.SearchStrategy[DataType]
) -> List[Param[UnaryParamContext]]:
    strat = xps.arrays(dtype=dtypes_strat, shape=hh.shapes())
    func_ctx = UnaryParamContext(
        func_name=elwise_func_name, func=getattr(xp, elwise_func_name), strat=strat
    )
    op_name = func_to_op[elwise_func_name]
    op_ctx = UnaryParamContext(
        func_name=op_name, func=lambda x: getattr(x, op_name)(), strat=strat
    )
    return [pytest.param(func_ctx, id=func_ctx.id), pytest.param(op_ctx, id=op_ctx.id)]


class FuncType(Enum):
    FUNC = auto()
    OP = auto()
    IOP = auto()


shapes_kw = {"min_side": 1}


class BinaryParamContext(NamedTuple):
    func_name: str
    func: Callable[[Array, Union[Scalar, Array]], Array]
    left_sym: str
    left_strat: st.SearchStrategy[Array]
    right_sym: str
    right_strat: st.SearchStrategy[Union[Scalar, Array]]
    right_is_scalar: bool
    res_name: str

    @property
    def id(self) -> str:
        return f"{self.func_name}({self.left_sym}, {self.right_sym})"

    def __repr__(self):
        return f"BinaryParamContext(<{self.id}>)"


def make_binary_params(
    elwise_func_name: str, dtypes_strat: st.SearchStrategy[DataType]
) -> List[Param[BinaryParamContext]]:
    def make_param(
        func_name: str, func_type: FuncType, right_is_scalar: bool
    ) -> Param[BinaryParamContext]:
        if right_is_scalar:
            left_sym = "x"
            right_sym = "s"
        else:
            left_sym = "x1"
            right_sym = "x2"

        shared_dtypes = st.shared(dtypes_strat)
        if right_is_scalar:
            left_strat = xps.arrays(dtype=shared_dtypes, shape=hh.shapes(**shapes_kw))
            right_strat = shared_dtypes.flatmap(
                lambda d: xps.from_dtype(d, **finite_kw)
            )
        else:
            if func_type is FuncType.IOP:
                shared_shapes = st.shared(hh.shapes(**shapes_kw))
                left_strat = xps.arrays(dtype=shared_dtypes, shape=shared_shapes)
                right_strat = xps.arrays(dtype=shared_dtypes, shape=shared_shapes)
            else:
                mutual_shapes = st.shared(
                    hh.mutually_broadcastable_shapes(2, **shapes_kw)
                )
                left_strat = xps.arrays(
                    dtype=shared_dtypes, shape=mutual_shapes.map(lambda pair: pair[0])
                )
                right_strat = xps.arrays(
                    dtype=shared_dtypes, shape=mutual_shapes.map(lambda pair: pair[1])
                )

        if func_type is FuncType.FUNC:
            func = getattr(xp, func_name)
        else:
            op_sym = all_op_to_symbol[func_name]
            expr = f"{left_sym} {op_sym} {right_sym}"
            if func_type is FuncType.OP:

                def func(l: Array, r: Union[Scalar, Array]) -> Array:
                    locals_ = {}
                    locals_[left_sym] = l
                    locals_[right_sym] = r
                    return eval(expr, locals_)

            else:

                def func(l: Array, r: Union[Scalar, Array]) -> Array:
                    locals_ = {}
                    locals_[left_sym] = ah.asarray(l, copy=True)  # prevents mutating l
                    locals_[right_sym] = r
                    exec(expr, locals_)
                    return locals_[left_sym]

            func.__name__ = func_name  # for repr

        if func_type is FuncType.IOP:
            res_name = left_sym
        else:
            res_name = "out"

        ctx = BinaryParamContext(
            func_name,
            func,
            left_sym,
            left_strat,
            right_sym,
            right_strat,
            right_is_scalar,
            res_name,
        )
        return pytest.param(ctx, id=ctx.id)

    op_name = func_to_op[elwise_func_name]
    params = [
        make_param(elwise_func_name, FuncType.FUNC, False),
        make_param(op_name, FuncType.OP, False),
        make_param(op_name, FuncType.OP, True),
    ]
    iop_name = f"__i{op_name[2:]}"
    if iop_name in dh.inplace_op_to_symbol.keys():
        params.append(make_param(iop_name, FuncType.IOP, False))
        params.append(make_param(iop_name, FuncType.IOP, True))

    return params


def binary_param_assert_dtype(
    ctx: BinaryParamContext,
    left: Array,
    right: Union[Array, Scalar],
    res: Array,
    expected: Optional[DataType] = None,
):
    if ctx.right_is_scalar:
        in_dtypes = left.dtype
    else:
        in_dtypes = [left.dtype, right.dtype]  # type: ignore
    ph.assert_dtype(
        ctx.func_name, in_dtypes, res.dtype, expected, repr_name=f"{ctx.res_name}.dtype"
    )


def binary_param_assert_shape(
    ctx: BinaryParamContext,
    left: Array,
    right: Union[Array, Scalar],
    res: Array,
    expected: Optional[Shape] = None,
):
    if ctx.right_is_scalar:
        in_shapes = [left.shape]
    else:
        in_shapes = [left.shape, right.shape]  # type: ignore
    ph.assert_result_shape(
        ctx.func_name, in_shapes, res.shape, expected, repr_name=f"{ctx.res_name}.shape"
    )


def binary_param_assert_against_refimpl(
    ctx: BinaryParamContext,
    left: Array,
    right: Union[Array, Scalar],
    res: Array,
    refimpl: Callable[[Scalar, Scalar], Scalar],
    expr_template: str,
    in_stype: Optional[ScalarType] = None,
    res_stype: Optional[ScalarType] = None,
    filter_: Callable[[Scalar], bool] = math.isfinite,
):
    if ctx.right_is_scalar:
        assert filter_(right)  # sanity check
        if left.dtype != xp.bool:
            m, M = dh.dtype_ranges[left.dtype]
        if in_stype is None:
            in_stype = dh.get_scalar_type(left.dtype)
        if res_stype is None:
            res_stype = in_stype
        for idx in sh.ndindex(res.shape):
            scalar_l = in_stype(left[idx])
            if not filter_(scalar_l):
                continue
            expected = refimpl(scalar_l, right)
            if left.dtype != xp.bool:
                if expected <= m or expected >= M:
                    continue
            scalar_o = res_stype(res[idx])
            f_l = sh.fmt_idx(ctx.left_sym, idx)
            f_o = sh.fmt_idx(ctx.res_name, idx)
            expr = expr_template.format(f_l, right, expected)
            if dh.is_float_dtype(left.dtype):
                assert isclose(scalar_o, expected), (
                    f"{f_o}={scalar_o}, but should be roughly {expr} "
                    f"[{ctx.func_name}()]\n"
                    f"{f_l}={scalar_l}"
                )
            else:
                assert scalar_o == expected, (
                    f"{f_o}={scalar_o}, but should be {expr} "
                    f"[{ctx.func_name}()]\n"
                    f"{f_l}={scalar_l}"
                )
    else:
        binary_assert_against_refimpl(
            func_name=ctx.func_name,
            in_stype=in_stype,
            left_sym=ctx.left_sym,
            left=left,
            right_sym=ctx.right_sym,
            right=right,
            res_stype=res_stype,
            res_name=ctx.res_name,
            res=res,
            refimpl=refimpl,
            expr_template=expr_template,
            filter_=filter_,
        )


@pytest.mark.parametrize("ctx", make_unary_params("abs", xps.numeric_dtypes()))
@given(data=st.data())
def test_abs(ctx, data):
    x = data.draw(ctx.strat, label="x")
    # abs of the smallest negative integer is out-of-scope
    if x.dtype in dh.int_dtypes:
        assume(xp.all(x > dh.dtype_ranges[x.dtype].min))

    out = ctx.func(x)

    ph.assert_dtype(ctx.func_name, x.dtype, out.dtype)
    ph.assert_shape(ctx.func_name, out.shape, x.shape)
    unary_assert_against_refimpl(
        ctx.func_name,
        x,
        out,
        abs,
        "abs({})={}",
        filter_=lambda s: (
            s == float("infinity") or (math.isfinite(s) and s is not -0.0)
        ),
    )


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_acos(x):
    res = xp.acos(x)
    ph.assert_dtype("acos", x.dtype, res.dtype)
    ph.assert_shape("acos", res.shape, x.shape)
    ONE = ah.one(x.shape, x.dtype)
    # Here (and elsewhere), should technically be res.dtype, but this is the
    # same as x.dtype, as tested by the type_promotion tests.
    PI = ah.π(x.shape, x.dtype)
    ZERO = ah.zero(x.shape, x.dtype)
    domain = ah.inrange(x, -ONE, ONE)
    codomain = ah.inrange(res, ZERO, PI)
    # acos maps [-1, 1] to [0, pi]. Values outside this domain are mapped to
    # nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_acosh(x):
    res = xp.acosh(x)
    ph.assert_dtype("acosh", x.dtype, res.dtype)
    ph.assert_shape("acosh", res.shape, x.shape)
    ONE = ah.one(x.shape, x.dtype)
    INFINITY = ah.infinity(x.shape, x.dtype)
    ZERO = ah.zero(x.shape, x.dtype)
    domain = ah.inrange(x, ONE, INFINITY)
    codomain = ah.inrange(res, ZERO, INFINITY)
    # acosh maps [-1, inf] to [0, inf]. Values outside this domain are mapped
    # to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@pytest.mark.parametrize("ctx,", make_binary_params("add", xps.numeric_dtypes()))
@given(data=st.data())
def test_add(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    try:
        res = ctx.func(left, right)
    except OverflowError:
        reject()

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    binary_param_assert_against_refimpl(
        ctx, left, right, res, operator.add, "({} + {})={}"
    )


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_asin(x):
    out = xp.asin(x)
    ph.assert_dtype("asin", x.dtype, out.dtype)
    ph.assert_shape("asin", out.shape, x.shape)
    ONE = ah.one(x.shape, x.dtype)
    PI = ah.π(x.shape, x.dtype)
    domain = ah.inrange(x, -ONE, ONE)
    codomain = ah.inrange(out, -PI / 2, PI / 2)
    # asin maps [-1, 1] to [-pi/2, pi/2]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_asinh(x):
    out = xp.asinh(x)
    ph.assert_dtype("asinh", x.dtype, out.dtype)
    ph.assert_shape("asinh", out.shape, x.shape)
    INFINITY = ah.infinity(x.shape, x.dtype)
    domain = ah.inrange(x, -INFINITY, INFINITY)
    codomain = ah.inrange(out, -INFINITY, INFINITY)
    # asinh maps [-inf, inf] to [-inf, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_atan(x):
    out = xp.atan(x)
    ph.assert_dtype("atan", x.dtype, out.dtype)
    ph.assert_shape("atan", out.shape, x.shape)
    INFINITY = ah.infinity(x.shape, x.dtype)
    PI = ah.π(x.shape, x.dtype)
    domain = ah.inrange(x, -INFINITY, INFINITY)
    codomain = ah.inrange(out, -PI / 2, PI / 2)
    # atan maps [-inf, inf] to [-pi/2, pi/2]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(*hh.two_mutual_arrays(dh.float_dtypes))
def test_atan2(x1, x2):
    out = xp.atan2(x1, x2)
    ph.assert_dtype("atan2", [x1.dtype, x2.dtype], out.dtype)
    ph.assert_result_shape("atan2", [x1.shape, x2.shape], out.shape)
    INFINITY1 = ah.infinity(x1.shape, x1.dtype)
    INFINITY2 = ah.infinity(x2.shape, x2.dtype)
    PI = ah.π(out.shape, out.dtype)
    domainx1 = ah.inrange(x1, -INFINITY1, INFINITY1)
    domainx2 = ah.inrange(x2, -INFINITY2, INFINITY2)
    # codomain = ah.inrange(out, -PI, PI, 1e-5)
    codomain = ah.inrange(out, -PI, PI)
    # atan2 maps [-inf, inf] x [-inf, inf] to [-pi, pi]. Values outside
    # this domain are mapped to nan, which is already tested in the special
    # cases.
    ah.assert_exactly_equal(ah.logical_and(domainx1, domainx2), codomain)
    # From the spec:
    #
    # The mathematical signs of `x1_i` and `x2_i` determine the quadrant of
    # each element-wise out. The quadrant (i.e., branch) is chosen such
    # that each element-wise out is the signed angle in radians between the
    # ray ending at the origin and passing through the point `(1,0)` and the
    # ray ending at the origin and passing through the point `(x2_i, x1_i)`.

    # This is equivalent to atan2(x1, x2) has the same sign as x1 when x2 is
    # finite.
    pos_x1 = ah.positive_mathematical_sign(x1)
    neg_x1 = ah.negative_mathematical_sign(x1)
    pos_x2 = ah.positive_mathematical_sign(x2)
    neg_x2 = ah.negative_mathematical_sign(x2)
    pos_out = ah.positive_mathematical_sign(out)
    neg_out = ah.negative_mathematical_sign(out)
    ah.assert_exactly_equal(
        ah.logical_or(ah.logical_and(pos_x1, pos_x2), ah.logical_and(pos_x1, neg_x2)),
        pos_out,
    )
    ah.assert_exactly_equal(
        ah.logical_or(ah.logical_and(neg_x1, pos_x2), ah.logical_and(neg_x1, neg_x2)),
        neg_out,
    )


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_atanh(x):
    out = xp.atanh(x)
    ph.assert_dtype("atanh", x.dtype, out.dtype)
    ph.assert_shape("atanh", out.shape, x.shape)
    ONE = ah.one(x.shape, x.dtype)
    INFINITY = ah.infinity(x.shape, x.dtype)
    domain = ah.inrange(x, -ONE, ONE)
    codomain = ah.inrange(out, -INFINITY, INFINITY)
    # atanh maps [-1, 1] to [-inf, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@pytest.mark.parametrize(
    "ctx", make_binary_params("bitwise_and", boolean_and_all_integer_dtypes())
)
@given(data=st.data())
def test_bitwise_and(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    if left.dtype == xp.bool:
        refimpl = lambda l, r: l and r
    else:
        refimpl = lambda l, r: mock_int_dtype(l & r, res.dtype)
    binary_param_assert_against_refimpl(ctx, left, right, res, refimpl, "({} & {})={}")


@pytest.mark.parametrize(
    "ctx", make_binary_params("bitwise_left_shift", all_integer_dtypes())
)
@given(data=st.data())
def test_bitwise_left_shift(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)
    if ctx.right_is_scalar:
        assume(right >= 0)
    else:
        assume(not ah.any(ah.isnegative(right)))

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    binary_param_assert_against_refimpl(
        ctx,
        left,
        right,
        res,
        lambda l, r: mock_int_dtype(l << r, res.dtype)
        if r < dh.dtype_nbits[res.dtype]
        else 0,
        "({} << {})={}",
    )


@pytest.mark.parametrize(
    "ctx", make_unary_params("bitwise_invert", boolean_and_all_integer_dtypes())
)
@given(data=st.data())
def test_bitwise_invert(ctx, data):
    x = data.draw(ctx.strat, label="x")

    out = ctx.func(x)

    ph.assert_dtype(ctx.func_name, x.dtype, out.dtype)
    ph.assert_shape(ctx.func_name, out.shape, x.shape)
    if x.dtype == xp.bool:
        refimpl = lambda s: not s
    else:
        refimpl = lambda s: mock_int_dtype(~s, x.dtype)
    unary_assert_against_refimpl(ctx.func_name, x, out, refimpl, "~{}={}")


@pytest.mark.parametrize(
    "ctx", make_binary_params("bitwise_or", boolean_and_all_integer_dtypes())
)
@given(data=st.data())
def test_bitwise_or(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    if left.dtype == xp.bool:
        refimpl = lambda l, r: l or r
    else:
        refimpl = lambda l, r: mock_int_dtype(l | r, res.dtype)
    binary_param_assert_against_refimpl(ctx, left, right, res, refimpl, "({} | {})={}")


@pytest.mark.parametrize(
    "ctx", make_binary_params("bitwise_right_shift", all_integer_dtypes())
)
@given(data=st.data())
def test_bitwise_right_shift(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)
    if ctx.right_is_scalar:
        assume(right >= 0)
    else:
        assume(not ah.any(ah.isnegative(right)))

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    binary_param_assert_against_refimpl(
        ctx,
        left,
        right,
        res,
        lambda l, r: mock_int_dtype(l >> r, res.dtype),
        "({} >> {})={}",
    )


@pytest.mark.parametrize(
    "ctx", make_binary_params("bitwise_xor", boolean_and_all_integer_dtypes())
)
@given(data=st.data())
def test_bitwise_xor(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    if left.dtype == xp.bool:
        refimpl = lambda l, r: l ^ r
    else:
        refimpl = lambda l, r: mock_int_dtype(l ^ r, res.dtype)
    binary_param_assert_against_refimpl(ctx, left, right, res, refimpl, "({} ^ {})={}")


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_ceil(x):
    # This test is almost identical to test_floor()
    out = xp.ceil(x)
    ph.assert_dtype("ceil", x.dtype, out.dtype)
    ph.assert_shape("ceil", out.shape, x.shape)
    finite = ah.isfinite(x)
    ah.assert_integral(out[finite])
    assert ah.all(ah.less_equal(x[finite], out[finite]))
    assert ah.all(
        ah.less_equal(out[finite] - x[finite], ah.one(x[finite].shape, x.dtype))
    )
    integers = ah.isintegral(x)
    ah.assert_exactly_equal(out[integers], x[integers])


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_cos(x):
    out = xp.cos(x)
    ph.assert_dtype("cos", x.dtype, out.dtype)
    ph.assert_shape("cos", out.shape, x.shape)
    ONE = ah.one(x.shape, x.dtype)
    INFINITY = ah.infinity(x.shape, x.dtype)
    domain = ah.inrange(x, -INFINITY, INFINITY, open=True)
    codomain = ah.inrange(out, -ONE, ONE)
    # cos maps (-inf, inf) to [-1, 1]. Values outside this domain are mapped
    # to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_cosh(x):
    out = xp.cosh(x)
    ph.assert_dtype("cosh", x.dtype, out.dtype)
    ph.assert_shape("cosh", out.shape, x.shape)
    INFINITY = ah.infinity(x.shape, x.dtype)
    domain = ah.inrange(x, -INFINITY, INFINITY)
    codomain = ah.inrange(out, -INFINITY, INFINITY)
    # cosh maps [-inf, inf] to [-inf, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@pytest.mark.parametrize("ctx", make_binary_params("divide", xps.floating_dtypes()))
@given(data=st.data())
def test_divide(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    # There isn't much we can test here. The spec doesn't require any behavior
    # beyond the special cases, and indeed, there aren't many mathematical
    # properties of division that strictly hold for floating-point numbers. We
    # could test that this does implement IEEE 754 division, but we don't yet
    # have those sorts in general for this module.


@pytest.mark.parametrize("ctx", make_binary_params("equal", xps.scalar_dtypes()))
@given(data=st.data())
def test_equal(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    out = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, out, xp.bool)
    binary_param_assert_shape(ctx, left, right, out)
    if not ctx.right_is_scalar:
        # We manually promote the dtypes as incorrect internal type promotion
        # could lead to false positives. For example
        #
        #     >>> xp.equal(
        #     ...     xp.asarray(1.0, dtype=xp.float32),
        #     ...     xp.asarray(1.00000001, dtype=xp.float64),
        #     ... )
        #
        # would erroneously be True if float64 downcasted to float32.
        promoted_dtype = dh.promotion_table[left.dtype, right.dtype]
        left = xp.astype(left, promoted_dtype)
        right = xp.astype(right, promoted_dtype)
    binary_param_assert_against_refimpl(
        ctx, left, right, out, operator.eq, "({} == {})={}", res_stype=bool
    )


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_exp(x):
    out = xp.exp(x)
    ph.assert_dtype("exp", x.dtype, out.dtype)
    ph.assert_shape("exp", out.shape, x.shape)
    INFINITY = ah.infinity(x.shape, x.dtype)
    ZERO = ah.zero(x.shape, x.dtype)
    domain = ah.inrange(x, -INFINITY, INFINITY)
    codomain = ah.inrange(out, ZERO, INFINITY)
    # exp maps [-inf, inf] to [0, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_expm1(x):
    out = xp.expm1(x)
    ph.assert_dtype("expm1", x.dtype, out.dtype)
    ph.assert_shape("expm1", out.shape, x.shape)
    INFINITY = ah.infinity(x.shape, x.dtype)
    NEGONE = -ah.one(x.shape, x.dtype)
    domain = ah.inrange(x, -INFINITY, INFINITY)
    codomain = ah.inrange(out, NEGONE, INFINITY)
    # expm1 maps [-inf, inf] to [1, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_floor(x):
    # This test is almost identical to test_ceil
    out = xp.floor(x)
    ph.assert_dtype("floor", x.dtype, out.dtype)
    ph.assert_shape("floor", out.shape, x.shape)
    finite = ah.isfinite(x)
    ah.assert_integral(out[finite])
    assert ah.all(ah.less_equal(out[finite], x[finite]))
    assert ah.all(
        ah.less_equal(x[finite] - out[finite], ah.one(x[finite].shape, x.dtype))
    )
    integers = ah.isintegral(x)
    ah.assert_exactly_equal(out[integers], x[integers])


@pytest.mark.parametrize(
    "ctx", make_binary_params("floor_divide", xps.numeric_dtypes())
)
@given(data=st.data())
def test_floor_divide(ctx, data):
    left = data.draw(
        ctx.left_strat.filter(lambda x: not ah.any(x == 0)), label=ctx.left_sym
    )
    right = data.draw(ctx.right_strat, label=ctx.right_sym)
    if ctx.right_is_scalar:
        assume(right != 0)
    else:
        assume(not ah.any(right == 0))

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    binary_param_assert_against_refimpl(
        ctx, left, right, res, operator.floordiv, "({} // {})={}"
    )


@pytest.mark.parametrize("ctx", make_binary_params("greater", xps.numeric_dtypes()))
@given(data=st.data())
def test_greater(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    out = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, out, xp.bool)
    binary_param_assert_shape(ctx, left, right, out)
    if not ctx.right_is_scalar:
        # See test_equal note
        promoted_dtype = dh.promotion_table[left.dtype, right.dtype]
        left = xp.astype(left, promoted_dtype)
        right = xp.astype(right, promoted_dtype)
    binary_param_assert_against_refimpl(
        ctx, left, right, out, operator.gt, "({} > {})={}", res_stype=bool
    )


@pytest.mark.parametrize(
    "ctx", make_binary_params("greater_equal", xps.numeric_dtypes())
)
@given(data=st.data())
def test_greater_equal(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    out = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, out, xp.bool)
    binary_param_assert_shape(ctx, left, right, out)
    if not ctx.right_is_scalar:
        # See test_equal note
        promoted_dtype = dh.promotion_table[left.dtype, right.dtype]
        left = xp.astype(left, promoted_dtype)
        right = xp.astype(right, promoted_dtype)
    binary_param_assert_against_refimpl(
        ctx, left, right, out, operator.ge, "({} >= {})={}", res_stype=bool
    )


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_isfinite(x):
    out = ah.isfinite(x)
    ph.assert_dtype("isfinite", x.dtype, out.dtype, xp.bool)
    ph.assert_shape("isfinite", out.shape, x.shape)
    if dh.is_int_dtype(x.dtype):
        ah.assert_exactly_equal(out, ah.true(x.shape))
    # Test that isfinite, isinf, and isnan are self-consistent.
    inf = ah.logical_or(xp.isinf(x), ah.isnan(x))
    ah.assert_exactly_equal(out, ah.logical_not(inf))

    # Test the exact value by comparing to the math version
    if dh.is_float_dtype(x.dtype):
        for idx in sh.ndindex(x.shape):
            s = float(x[idx])
            assert bool(out[idx]) == math.isfinite(s)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_isinf(x):
    out = xp.isinf(x)

    ph.assert_dtype("isfinite", x.dtype, out.dtype, xp.bool)
    ph.assert_shape("isinf", out.shape, x.shape)

    if dh.is_int_dtype(x.dtype):
        ah.assert_exactly_equal(out, ah.false(x.shape))
    finite_or_nan = ah.logical_or(ah.isfinite(x), ah.isnan(x))
    ah.assert_exactly_equal(out, ah.logical_not(finite_or_nan))

    # Test the exact value by comparing to the math version
    if dh.is_float_dtype(x.dtype):
        for idx in sh.ndindex(x.shape):
            s = float(x[idx])
            assert bool(out[idx]) == math.isinf(s)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_isnan(x):
    out = ah.isnan(x)

    ph.assert_dtype("isnan", x.dtype, out.dtype, xp.bool)
    ph.assert_shape("isnan", out.shape, x.shape)

    if dh.is_int_dtype(x.dtype):
        ah.assert_exactly_equal(out, ah.false(x.shape))
    finite_or_inf = ah.logical_or(ah.isfinite(x), xp.isinf(x))
    ah.assert_exactly_equal(out, ah.logical_not(finite_or_inf))

    # Test the exact value by comparing to the math version
    if dh.is_float_dtype(x.dtype):
        for idx in sh.ndindex(x.shape):
            s = float(x[idx])
            assert bool(out[idx]) == math.isnan(s)


@pytest.mark.parametrize("ctx", make_binary_params("less", xps.numeric_dtypes()))
@given(data=st.data())
def test_less(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    out = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, out, xp.bool)
    binary_param_assert_shape(ctx, left, right, out)
    if not ctx.right_is_scalar:
        # See test_equal note
        promoted_dtype = dh.promotion_table[left.dtype, right.dtype]
        left = xp.astype(left, promoted_dtype)
        right = xp.astype(right, promoted_dtype)
    binary_param_assert_against_refimpl(
        ctx, left, right, out, operator.lt, "({} < {})={}", res_stype=bool
    )


@pytest.mark.parametrize("ctx", make_binary_params("less_equal", xps.numeric_dtypes()))
@given(data=st.data())
def test_less_equal(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    out = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, out, xp.bool)
    binary_param_assert_shape(ctx, left, right, out)
    if not ctx.right_is_scalar:
        # See test_equal note
        promoted_dtype = dh.promotion_table[left.dtype, right.dtype]
        left = xp.astype(left, promoted_dtype)
        right = xp.astype(right, promoted_dtype)
    binary_param_assert_against_refimpl(
        ctx, left, right, out, operator.le, "({} <= {})={}", res_stype=bool
    )


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_log(x):
    out = xp.log(x)

    ph.assert_dtype("log", x.dtype, out.dtype)
    ph.assert_shape("log", out.shape, x.shape)

    INFINITY = ah.infinity(x.shape, x.dtype)
    ZERO = ah.zero(x.shape, x.dtype)
    domain = ah.inrange(x, ZERO, INFINITY)
    codomain = ah.inrange(out, -INFINITY, INFINITY)
    # log maps [0, inf] to [-inf, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_log1p(x):
    out = xp.log1p(x)
    ph.assert_dtype("log1p", x.dtype, out.dtype)
    ph.assert_shape("log1p", out.shape, x.shape)
    INFINITY = ah.infinity(x.shape, x.dtype)
    NEGONE = -ah.one(x.shape, x.dtype)
    codomain = ah.inrange(x, NEGONE, INFINITY)
    domain = ah.inrange(out, -INFINITY, INFINITY)
    # log1p maps [1, inf] to [-inf, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_log2(x):
    out = xp.log2(x)
    ph.assert_dtype("log2", x.dtype, out.dtype)
    ph.assert_shape("log2", out.shape, x.shape)
    INFINITY = ah.infinity(x.shape, x.dtype)
    ZERO = ah.zero(x.shape, x.dtype)
    domain = ah.inrange(x, ZERO, INFINITY)
    codomain = ah.inrange(out, -INFINITY, INFINITY)
    # log2 maps [0, inf] to [-inf, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_log10(x):
    out = xp.log10(x)
    ph.assert_dtype("log10", x.dtype, out.dtype)
    ph.assert_shape("log10", out.shape, x.shape)
    INFINITY = ah.infinity(x.shape, x.dtype)
    ZERO = ah.zero(x.shape, x.dtype)
    domain = ah.inrange(x, ZERO, INFINITY)
    codomain = ah.inrange(out, -INFINITY, INFINITY)
    # log10 maps [0, inf] to [-inf, inf]. Values outside this domain are
    # mapped to nan, which is already tested in the special cases.
    ah.assert_exactly_equal(domain, codomain)


@given(*hh.two_mutual_arrays(dh.float_dtypes))
def test_logaddexp(x1, x2):
    out = xp.logaddexp(x1, x2)
    ph.assert_dtype("logaddexp", [x1.dtype, x2.dtype], out.dtype)
    # The spec doesn't require any behavior for this function. We could test
    # that this is indeed an approximation of log(exp(x1) + exp(x2)), but we
    # don't have tests for this sort of thing for any functions yet.


@given(*hh.two_mutual_arrays([xp.bool]))
def test_logical_and(x1, x2):
    out = ah.logical_and(x1, x2)
    ph.assert_dtype("logical_and", [x1.dtype, x2.dtype], out.dtype)
    ph.assert_result_shape("logical_and", [x1.shape, x2.shape], out.shape)
    binary_assert_against_refimpl(
        "logical_and", x1, x2, out, lambda l, r: l and r, "({} and {})={}"
    )


@given(xps.arrays(dtype=xp.bool, shape=hh.shapes()))
def test_logical_not(x):
    out = ah.logical_not(x)
    ph.assert_dtype("logical_not", x.dtype, out.dtype)
    ph.assert_shape("logical_not", out.shape, x.shape)
    unary_assert_against_refimpl("logical_not", x, out, lambda i: not i, "(not {})={}")


@given(*hh.two_mutual_arrays([xp.bool]))
def test_logical_or(x1, x2):
    out = ah.logical_or(x1, x2)
    ph.assert_dtype("logical_or", [x1.dtype, x2.dtype], out.dtype)
    ph.assert_result_shape("logical_or", [x1.shape, x2.shape], out.shape)
    binary_assert_against_refimpl(
        "logical_or", x1, x2, out, lambda l, r: l or r, "({} or {})={}"
    )


@given(*hh.two_mutual_arrays([xp.bool]))
def test_logical_xor(x1, x2):
    out = xp.logical_xor(x1, x2)
    ph.assert_dtype("logical_xor", [x1.dtype, x2.dtype], out.dtype)
    ph.assert_result_shape("logical_xor", [x1.shape, x2.shape], out.shape)
    binary_assert_against_refimpl(
        "logical_xor", x1, x2, out, lambda l, r: l ^ r, "({} ^ {})={}"
    )


@pytest.mark.parametrize("ctx", make_binary_params("multiply", xps.numeric_dtypes()))
@given(data=st.data())
def test_multiply(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    binary_param_assert_against_refimpl(
        ctx, left, right, res, operator.mul, "({} * {})={}"
    )


@pytest.mark.parametrize(
    "ctx", make_unary_params("negative", xps.integer_dtypes() | xps.floating_dtypes())
)
@given(data=st.data())
def test_negative(ctx, data):
    x = data.draw(ctx.strat, label="x")
    # negative of the smallest negative integer is out-of-scope
    if x.dtype in dh.int_dtypes:
        assume(xp.all(x > dh.dtype_ranges[x.dtype].min))

    out = ctx.func(x)

    ph.assert_dtype(ctx.func_name, x.dtype, out.dtype)
    ph.assert_shape(ctx.func_name, out.shape, x.shape)
    unary_assert_against_refimpl(ctx.func_name, x, out, operator.neg, "-({})={}")


@pytest.mark.parametrize("ctx", make_binary_params("not_equal", xps.scalar_dtypes()))
@given(data=st.data())
def test_not_equal(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    out = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, out, xp.bool)
    binary_param_assert_shape(ctx, left, right, out)
    if not ctx.right_is_scalar:
        # See test_equal note
        promoted_dtype = dh.promotion_table[left.dtype, right.dtype]
        left = xp.astype(left, promoted_dtype)
        right = xp.astype(right, promoted_dtype)
    binary_param_assert_against_refimpl(
        ctx, left, right, out, operator.ne, "({} != {})={}", res_stype=bool
    )


@pytest.mark.parametrize("ctx", make_unary_params("positive", xps.numeric_dtypes()))
@given(data=st.data())
def test_positive(ctx, data):
    x = data.draw(ctx.strat, label="x")

    out = ctx.func(x)

    ph.assert_dtype(ctx.func_name, x.dtype, out.dtype)
    ph.assert_shape(ctx.func_name, out.shape, x.shape)
    ph.assert_array(ctx.func_name, out, x)


@pytest.mark.parametrize("ctx", make_binary_params("pow", xps.numeric_dtypes()))
@given(data=st.data())
def test_pow(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)
    if ctx.right_is_scalar:
        if isinstance(right, int):
            assume(right >= 0)
    else:
        if dh.is_int_dtype(right.dtype):
            assume(xp.all(right >= 0))

    try:
        res = ctx.func(left, right)
    except OverflowError:
        reject()

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    # There isn't much we can test here. The spec doesn't require any behavior
    # beyond the special cases, and indeed, there aren't many mathematical
    # properties of exponentiation that strictly hold for floating-point
    # numbers. We could test that this does implement IEEE 754 pow, but we
    # don't yet have those sorts in general for this module.


@pytest.mark.parametrize("ctx", make_binary_params("remainder", xps.numeric_dtypes()))
@given(data=st.data())
def test_remainder(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)
    if ctx.right_is_scalar:
        assume(right != 0)
    else:
        assume(not ah.any(right == 0))

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    binary_param_assert_against_refimpl(
        ctx, left, right, res, operator.mod, "({} % {})={}"
    )


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_round(x):
    out = xp.round(x)

    ph.assert_dtype("round", x.dtype, out.dtype)

    ph.assert_shape("round", out.shape, x.shape)

    # Test that the out is integral
    finite = ah.isfinite(x)
    ah.assert_integral(out[finite])

    # round(x) should be the neaoutt integer to x. The case where there is a
    # tie (round to even) is already handled by the special cases tests.

    # This is the same strategy used in the mask in the
    # test_round_special_cases_one_arg_two_integers_equally_close special
    # cases test.
    floor = xp.floor(x)
    ceil = xp.ceil(x)
    over = xp.subtract(x, floor)
    under = xp.subtract(ceil, x)
    round_down = ah.less(over, under)
    round_up = ah.less(under, over)
    ah.assert_exactly_equal(out[round_down], floor[round_down])
    ah.assert_exactly_equal(out[round_up], ceil[round_up])


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_sign(x):
    out = xp.sign(x)
    ph.assert_dtype("sign", x.dtype, out.dtype)
    ph.assert_shape("sign", out.shape, x.shape)
    scalar_type = dh.get_scalar_type(x.dtype)
    for idx in sh.ndindex(x.shape):
        scalar_x = scalar_type(x[idx])
        f_x = sh.fmt_idx("x", idx)
        if math.isnan(scalar_x):
            continue
        if scalar_x == 0:
            expected = 0
            expr = f"{f_x}=0"
        else:
            expected = 1 if scalar_x > 0 else -1
            expr = f"({f_x} / |{f_x}|)={expected}"
        scalar_o = scalar_type(out[idx])
        f_o = sh.fmt_idx("out", idx)
        assert (
            scalar_o == expected
        ), f"{f_o}={scalar_o}, but should be {expr} [sign()]\n{f_x}={scalar_x}"


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_sin(x):
    out = xp.sin(x)
    ph.assert_dtype("sin", x.dtype, out.dtype)
    ph.assert_shape("sin", out.shape, x.shape)
    # TODO


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_sinh(x):
    out = xp.sinh(x)
    ph.assert_dtype("sinh", x.dtype, out.dtype)
    ph.assert_shape("sinh", out.shape, x.shape)
    # TODO


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_square(x):
    out = xp.square(x)
    ph.assert_dtype("square", x.dtype, out.dtype)
    ph.assert_shape("square", out.shape, x.shape)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_sqrt(x):
    out = xp.sqrt(x)
    ph.assert_dtype("sqrt", x.dtype, out.dtype)
    ph.assert_shape("sqrt", out.shape, x.shape)


@pytest.mark.parametrize("ctx", make_binary_params("subtract", xps.numeric_dtypes()))
@given(data=st.data())
def test_subtract(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    try:
        res = ctx.func(left, right)
    except OverflowError:
        reject()

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    binary_param_assert_against_refimpl(
        ctx, left, right, res, operator.sub, "({} - {})={}"
    )


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_tan(x):
    out = xp.tan(x)
    ph.assert_dtype("tan", x.dtype, out.dtype)
    ph.assert_shape("tan", out.shape, x.shape)
    # TODO


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_tanh(x):
    out = xp.tanh(x)
    ph.assert_dtype("tanh", x.dtype, out.dtype)
    ph.assert_shape("tanh", out.shape, x.shape)
    # TODO


@given(xps.arrays(dtype=hh.numeric_dtypes, shape=xps.array_shapes()))
def test_trunc(x):
    out = xp.trunc(x)
    ph.assert_dtype("trunc", x.dtype, out.dtype)
    ph.assert_shape("trunc", out.shape, x.shape)
    if dh.is_int_dtype(x.dtype):
        ah.assert_exactly_equal(out, x)
    else:
        finite = ah.isfinite(x)
        ah.assert_integral(out[finite])
