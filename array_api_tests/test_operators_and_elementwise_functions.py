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
    """Returns equivalent of `n` that mocks `dtype` behaviour."""
    nbits = dh.dtype_nbits[dtype]
    mask = (1 << nbits) - 1
    n &= mask
    if dh.dtype_signed[dtype]:
        highest_bit = 1 << (nbits - 1)
        if n & highest_bit:
            n = -((~n & mask) + 1)
    return n


def default_filter(s: Scalar) -> bool:
    """Returns False when s is a non-finite or a signed zero.

    Used by default as these values are typically special-cased.
    """
    return math.isfinite(s) and s is not -0.0 and s is not +0.0


def unary_assert_against_refimpl(
    func_name: str,
    in_: Array,
    res: Array,
    refimpl: Callable[[Scalar], Scalar],
    expr_template: Optional[str] = None,
    res_stype: Optional[ScalarType] = None,
    filter_: Callable[[Scalar], bool] = default_filter,
    strict_check: bool = False,
):
    if in_.shape != res.shape:
        raise ValueError(f"{res.shape=}, but should be {in_.shape=}")
    if expr_template is None:
        expr_template = func_name + "({})={}"
    in_stype = dh.get_scalar_type(in_.dtype)
    if res_stype is None:
        res_stype = in_stype
    m, M = dh.dtype_ranges.get(res.dtype, (None, None))
    for idx in sh.ndindex(in_.shape):
        scalar_i = in_stype(in_[idx])
        if not filter_(scalar_i):
            continue
        try:
            expected = refimpl(scalar_i)
        except OverflowError:
            continue
        if res.dtype != xp.bool:
            assert m is not None and M is not None  # for mypy
            if expected <= m or expected >= M:
                continue
        scalar_o = res_stype(res[idx])
        f_i = sh.fmt_idx("x", idx)
        f_o = sh.fmt_idx("out", idx)
        expr = expr_template.format(f_i, expected)
        if not strict_check and dh.is_float_dtype(res.dtype):
            assert isclose(scalar_o, expected), (
                f"{f_o}={scalar_o}, but should be roughly {expr} [{func_name}()]\n"
                f"{f_i}={scalar_i}"
            )
        else:
            assert scalar_o == expected, (
                f"{f_o}={scalar_o}, but should be {expr} [{func_name}()]\n"
                f"{f_i}={scalar_i}"
            )


def binary_assert_against_refimpl(
    func_name: str,
    left: Array,
    right: Array,
    res: Array,
    refimpl: Callable[[Scalar, Scalar], Scalar],
    expr_template: Optional[str] = None,
    res_stype: Optional[ScalarType] = None,
    left_sym: str = "x1",
    right_sym: str = "x2",
    res_name: str = "out",
    filter_: Callable[[Scalar], bool] = default_filter,
    strict_check: bool = False,
):
    if expr_template is None:
        expr_template = func_name + "({}, {})={}"
    in_stype = dh.get_scalar_type(left.dtype)
    if res_stype is None:
        res_stype = in_stype
    m, M = dh.dtype_ranges.get(res.dtype, (None, None))
    for l_idx, r_idx, o_idx in sh.iter_indices(left.shape, right.shape, res.shape):
        scalar_l = in_stype(left[l_idx])
        scalar_r = in_stype(right[r_idx])
        if not (filter_(scalar_l) and filter_(scalar_r)):
            continue
        try:
            expected = refimpl(scalar_l, scalar_r)
        except OverflowError:
            continue
        if res.dtype != xp.bool:
            assert m is not None and M is not None  # for mypy
            if expected <= m or expected >= M:
                continue
        scalar_o = res_stype(res[o_idx])
        f_l = sh.fmt_idx(left_sym, l_idx)
        f_r = sh.fmt_idx(right_sym, r_idx)
        f_o = sh.fmt_idx(res_name, o_idx)
        expr = expr_template.format(f_l, f_r, expected)
        if not strict_check and dh.is_float_dtype(res.dtype):
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
    op_sym: str,
    refimpl: Callable[[Scalar, Scalar], Scalar],
    res_stype: Optional[ScalarType] = None,
    filter_: Callable[[Scalar], bool] = default_filter,
    strict_check: bool = False,
):
    expr_template = "({} " + op_sym + " {})={}"
    if ctx.right_is_scalar:
        assert filter_(right)  # sanity check
        in_stype = dh.get_scalar_type(left.dtype)
        if res_stype is None:
            res_stype = in_stype
        m, M = dh.dtype_ranges.get(left.dtype, (None, None))
        for idx in sh.ndindex(res.shape):
            scalar_l = in_stype(left[idx])
            if not filter_(scalar_l):
                continue
            try:
                expected = refimpl(scalar_l, right)
            except OverflowError:
                continue
            if left.dtype != xp.bool:
                assert m is not None and M is not None  # for mypy
                if expected <= m or expected >= M:
                    continue
            scalar_o = res_stype(res[idx])
            f_l = sh.fmt_idx(ctx.left_sym, idx)
            f_o = sh.fmt_idx(ctx.res_name, idx)
            expr = expr_template.format(f_l, right, expected)
            if not strict_check and dh.is_float_dtype(left.dtype):
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
            strict_check=strict_check,
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
        expr_template="abs({})={}",
        filter_=lambda s: (
            s == float("infinity") or (math.isfinite(s) and s is not -0.0)
        ),
    )


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(),
        shape=hh.shapes(),
        elements={"min_value": -1, "max_value": 1},
    )
)
def test_acos(x):
    out = xp.acos(x)
    ph.assert_dtype("acos", x.dtype, out.dtype)
    ph.assert_shape("acos", out.shape, x.shape)
    unary_assert_against_refimpl("acos", x, out, math.acos)


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(), shape=hh.shapes(), elements={"min_value": 1}
    )
)
def test_acosh(x):
    out = xp.acosh(x)
    ph.assert_dtype("acosh", x.dtype, out.dtype)
    ph.assert_shape("acosh", out.shape, x.shape)
    unary_assert_against_refimpl("acosh", x, out, math.acosh)


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
    binary_param_assert_against_refimpl(ctx, left, right, res, "+", operator.add)


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(),
        shape=hh.shapes(),
        elements={"min_value": -1, "max_value": 1},
    )
)
def test_asin(x):
    out = xp.asin(x)
    ph.assert_dtype("asin", x.dtype, out.dtype)
    ph.assert_shape("asin", out.shape, x.shape)
    unary_assert_against_refimpl("asin", x, out, math.asin)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_asinh(x):
    out = xp.asinh(x)
    ph.assert_dtype("asinh", x.dtype, out.dtype)
    ph.assert_shape("asinh", out.shape, x.shape)
    unary_assert_against_refimpl("asinh", x, out, math.asinh)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_atan(x):
    out = xp.atan(x)
    ph.assert_dtype("atan", x.dtype, out.dtype)
    ph.assert_shape("atan", out.shape, x.shape)
    unary_assert_against_refimpl("atan", x, out, math.atan)


@given(*hh.two_mutual_arrays(dh.float_dtypes))
def test_atan2(x1, x2):
    out = xp.atan2(x1, x2)
    ph.assert_dtype("atan2", [x1.dtype, x2.dtype], out.dtype)
    ph.assert_result_shape("atan2", [x1.shape, x2.shape], out.shape)
    binary_assert_against_refimpl("atan2", x1, x2, out, math.atan2)


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(),
        shape=hh.shapes(),
        elements={"min_value": -1, "max_value": 1},
    )
)
def test_atanh(x):
    out = xp.atanh(x)
    ph.assert_dtype("atanh", x.dtype, out.dtype)
    ph.assert_shape("atanh", out.shape, x.shape)
    unary_assert_against_refimpl("atanh", x, out, math.atanh)


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
    binary_param_assert_against_refimpl(ctx, left, right, res, "&", refimpl)


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
        "<<",
        lambda l, r: (
            mock_int_dtype(l << r, res.dtype) if r < dh.dtype_nbits[res.dtype] else 0
        ),
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
    unary_assert_against_refimpl(ctx.func_name, x, out, refimpl, expr_template="~{}={}")


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
    binary_param_assert_against_refimpl(ctx, left, right, res, "|", refimpl)


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
        ">>",
        lambda l, r: mock_int_dtype(l >> r, res.dtype),
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
        refimpl = operator.xor
    else:
        refimpl = lambda l, r: mock_int_dtype(l ^ r, res.dtype)
    binary_param_assert_against_refimpl(ctx, left, right, res, "^", refimpl)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_ceil(x):
    out = xp.ceil(x)
    ph.assert_dtype("ceil", x.dtype, out.dtype)
    ph.assert_shape("ceil", out.shape, x.shape)
    unary_assert_against_refimpl("ceil", x, out, math.ceil, strict_check=True)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_cos(x):
    out = xp.cos(x)
    ph.assert_dtype("cos", x.dtype, out.dtype)
    ph.assert_shape("cos", out.shape, x.shape)
    unary_assert_against_refimpl("cos", x, out, math.cos)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_cosh(x):
    out = xp.cosh(x)
    ph.assert_dtype("cosh", x.dtype, out.dtype)
    ph.assert_shape("cosh", out.shape, x.shape)
    unary_assert_against_refimpl("cosh", x, out, math.cosh)


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
        ctx, left, right, out, "==", operator.eq, res_stype=bool
    )


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_exp(x):
    out = xp.exp(x)
    ph.assert_dtype("exp", x.dtype, out.dtype)
    ph.assert_shape("exp", out.shape, x.shape)
    unary_assert_against_refimpl("exp", x, out, math.exp)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_expm1(x):
    out = xp.expm1(x)
    ph.assert_dtype("expm1", x.dtype, out.dtype)
    ph.assert_shape("expm1", out.shape, x.shape)
    unary_assert_against_refimpl("expm1", x, out, math.expm1)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_floor(x):
    out = xp.floor(x)
    ph.assert_dtype("floor", x.dtype, out.dtype)
    ph.assert_shape("floor", out.shape, x.shape)
    unary_assert_against_refimpl("floor", x, out, math.floor, strict_check=True)


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
    binary_param_assert_against_refimpl(ctx, left, right, res, "//", operator.floordiv)


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
        ctx, left, right, out, ">", operator.gt, res_stype=bool
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
        ctx, left, right, out, ">=", operator.ge, res_stype=bool
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
    unary_assert_against_refimpl("isinf", x, out, math.isinf, res_stype=bool)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_isnan(x):
    out = ah.isnan(x)
    ph.assert_dtype("isnan", x.dtype, out.dtype, xp.bool)
    ph.assert_shape("isnan", out.shape, x.shape)
    unary_assert_against_refimpl("isnan", x, out, math.isnan, res_stype=bool)


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
        ctx, left, right, out, "<", operator.lt, res_stype=bool
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
        ctx, left, right, out, "<=", operator.le, res_stype=bool
    )


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(), shape=hh.shapes(), elements={"min_value": 1}
    )
)
def test_log(x):
    out = xp.log(x)
    ph.assert_dtype("log", x.dtype, out.dtype)
    ph.assert_shape("log", out.shape, x.shape)
    unary_assert_against_refimpl("log", x, out, math.log)


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(), shape=hh.shapes(), elements={"min_value": 1}
    )
)
def test_log1p(x):
    out = xp.log1p(x)
    ph.assert_dtype("log1p", x.dtype, out.dtype)
    ph.assert_shape("log1p", out.shape, x.shape)
    unary_assert_against_refimpl("log1p", x, out, math.log1p)


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(),
        shape=hh.shapes(),
        elements={"min_value": 0, "exclude_min": True},
    )
)
def test_log2(x):
    out = xp.log2(x)
    ph.assert_dtype("log2", x.dtype, out.dtype)
    ph.assert_shape("log2", out.shape, x.shape)
    unary_assert_against_refimpl("log2", x, out, math.log2)


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(),
        shape=hh.shapes(),
        elements={"min_value": 0, "exclude_min": True},
    )
)
def test_log10(x):
    out = xp.log10(x)
    ph.assert_dtype("log10", x.dtype, out.dtype)
    ph.assert_shape("log10", out.shape, x.shape)
    unary_assert_against_refimpl("log10", x, out, math.log10)


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
        "logical_and", x1, x2, out, lambda l, r: l and r, expr_template="({} and {})={}"
    )


@given(xps.arrays(dtype=xp.bool, shape=hh.shapes()))
def test_logical_not(x):
    out = ah.logical_not(x)
    ph.assert_dtype("logical_not", x.dtype, out.dtype)
    ph.assert_shape("logical_not", out.shape, x.shape)
    unary_assert_against_refimpl(
        "logical_not", x, out, lambda i: not i, expr_template="(not {})={}"
    )


@given(*hh.two_mutual_arrays([xp.bool]))
def test_logical_or(x1, x2):
    out = ah.logical_or(x1, x2)
    ph.assert_dtype("logical_or", [x1.dtype, x2.dtype], out.dtype)
    ph.assert_result_shape("logical_or", [x1.shape, x2.shape], out.shape)
    binary_assert_against_refimpl(
        "logical_or", x1, x2, out, lambda l, r: l or r, expr_template="({} or {})={}"
    )


@given(*hh.two_mutual_arrays([xp.bool]))
def test_logical_xor(x1, x2):
    out = xp.logical_xor(x1, x2)
    ph.assert_dtype("logical_xor", [x1.dtype, x2.dtype], out.dtype)
    ph.assert_result_shape("logical_xor", [x1.shape, x2.shape], out.shape)
    binary_assert_against_refimpl(
        "logical_xor", x1, x2, out, operator.xor, expr_template="({} ^ {})={}"
    )


@pytest.mark.parametrize("ctx", make_binary_params("multiply", xps.numeric_dtypes()))
@given(data=st.data())
def test_multiply(ctx, data):
    left = data.draw(ctx.left_strat, label=ctx.left_sym)
    right = data.draw(ctx.right_strat, label=ctx.right_sym)

    res = ctx.func(left, right)

    binary_param_assert_dtype(ctx, left, right, res)
    binary_param_assert_shape(ctx, left, right, res)
    binary_param_assert_against_refimpl(ctx, left, right, res, "*", operator.mul)


# TODO: clarify if uints are acceptable, adjust accordingly
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
    unary_assert_against_refimpl(
        ctx.func_name, x, out, operator.neg, expr_template="-({})={}"
    )


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
        ctx, left, right, out, "!=", operator.ne, res_stype=bool
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
    binary_param_assert_against_refimpl(ctx, left, right, res, "%", operator.mod)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_round(x):
    out = xp.round(x)
    ph.assert_dtype("round", x.dtype, out.dtype)
    ph.assert_shape("round", out.shape, x.shape)
    unary_assert_against_refimpl("round", x, out, round, strict_check=True)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_sign(x):
    out = xp.sign(x)
    ph.assert_dtype("sign", x.dtype, out.dtype)
    ph.assert_shape("sign", out.shape, x.shape)
    scalar_type = dh.get_scalar_type(out.dtype)
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
    unary_assert_against_refimpl("sin", x, out, math.sin)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_sinh(x):
    out = xp.sinh(x)
    ph.assert_dtype("sinh", x.dtype, out.dtype)
    ph.assert_shape("sinh", out.shape, x.shape)
    unary_assert_against_refimpl("sinh", x, out, math.sinh)


@given(xps.arrays(dtype=xps.numeric_dtypes(), shape=hh.shapes()))
def test_square(x):
    out = xp.square(x)
    ph.assert_dtype("square", x.dtype, out.dtype)
    ph.assert_shape("square", out.shape, x.shape)
    unary_assert_against_refimpl(
        "square", x, out, lambda s: s ** 2, expr_template="{}²={}"
    )


@given(
    xps.arrays(
        dtype=xps.floating_dtypes(), shape=hh.shapes(), elements={"min_value": 0}
    )
)
def test_sqrt(x):
    out = xp.sqrt(x)
    ph.assert_dtype("sqrt", x.dtype, out.dtype)
    ph.assert_shape("sqrt", out.shape, x.shape)
    unary_assert_against_refimpl("sqrt", x, out, math.sqrt)


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
    binary_param_assert_against_refimpl(ctx, left, right, res, "-", operator.sub)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_tan(x):
    out = xp.tan(x)
    ph.assert_dtype("tan", x.dtype, out.dtype)
    ph.assert_shape("tan", out.shape, x.shape)
    unary_assert_against_refimpl("tan", x, out, math.tan)


@given(xps.arrays(dtype=xps.floating_dtypes(), shape=hh.shapes()))
def test_tanh(x):
    out = xp.tanh(x)
    ph.assert_dtype("tanh", x.dtype, out.dtype)
    ph.assert_shape("tanh", out.shape, x.shape)
    unary_assert_against_refimpl("tanh", x, out, math.tanh)


@given(xps.arrays(dtype=hh.numeric_dtypes, shape=xps.array_shapes()))
def test_trunc(x):
    out = xp.trunc(x)
    ph.assert_dtype("trunc", x.dtype, out.dtype)
    ph.assert_shape("trunc", out.shape, x.shape)
    unary_assert_against_refimpl("trunc", x, out, math.trunc, strict_check=True)
