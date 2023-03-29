"""
Tests for linalg functions

https://data-apis.org/array-api/latest/API_specification/linear_algebra_functions.html

and

https://data-apis.org/array-api/latest/extensions/linear_algebra_functions.html

Note: this file currently mixes both the required linear algebra functions and
functions from the linalg extension. The functions in the latter are not
required, but we don't yet have a clean way to disable only those tests (see https://github.com/data-apis/array-api-tests/issues/25).

"""

import pytest
from hypothesis import assume, given
from hypothesis.strategies import (booleans, composite, tuples, floats,
                                   integers, shared, sampled_from, one_of,
                                   data)
from ndindex import iter_indices

import itertools

from .array_helpers import assert_exactly_equal, asarray
from .hypothesis_helpers import (xps, dtypes, shapes, kwargs, matrix_shapes,
                                 square_matrix_shapes, symmetric_matrices,
                                 positive_definite_matrices, MAX_ARRAY_SIZE,
                                 invertible_matrices, two_mutual_arrays,
                                 mutually_promotable_dtypes, one_d_shapes,
                                 two_mutually_broadcastable_shapes,
                                 mutually_broadcastable_shapes,
                                 SQRT_MAX_ARRAY_SIZE, finite_matrices,
                                 rtol_shared_matrix_shapes, rtols, axes)
from . import dtype_helpers as dh
from . import pytest_helpers as ph
from . import shape_helpers as sh

from . import _array_module
from . import _array_module as xp
from ._array_module import linalg

pytestmark = pytest.mark.ci

def assert_equal(x, y, msg_extra=None):
    extra = '' if not msg_extra else f' ({msg_extra})'
    if x.dtype in dh.float_dtypes:
        # It's too difficult to do an approximately equal test here because
        # different routines can give completely different answers, and even
        # when it does work, the elementwise comparisons are too slow. So for
        # floating-point dtypes only test the shape and dtypes.

        # assert_allclose(x, y)

        assert x.shape == y.shape, f"The input arrays do not have the same shapes ({x.shape} != {y.shape}){extra}"
        assert x.dtype == y.dtype, f"The input arrays do not have the same dtype ({x.dtype} != {y.dtype}){extra}"
    else:
        assert_exactly_equal(x, y, msg_extra=msg_extra)

def _test_stacks(f, *args, res=None, dims=2, true_val=None,
                 matrix_axes=(-2, -1),
                 assert_equal=assert_equal, **kw):
    """
    Test that f(*args, **kw) maps across stacks of matrices

    dims is the number of dimensions f(*args, *kw) should have for a single n
    x m matrix stack.

    matrix_axes are the axes along which matrices (or vectors) are stacked in
    the input.

    true_val may be a function such that true_val(*x_stacks, **kw) gives the
    true value for f on a stack.

    res should be the result of f(*args, **kw). It is computed if not passed
    in.

    """
    if res is None:
        res = f(*args, **kw)

    shapes = [x.shape for x in args]

    # Assume the result is stacked along the last 'dims' axes of matrix_axes.
    # This holds for all the functions tested in this file
    res_axes = matrix_axes[::-1][:dims]

    for (x_idxes, (res_idx,)) in zip(
            iter_indices(*shapes, skip_axes=matrix_axes),
            iter_indices(res.shape, skip_axes=res_axes)):
        x_idxes = [x_idx.raw for x_idx in x_idxes]
        res_idx = res_idx.raw

        res_stack = res[res_idx]
        x_stacks = [x[x_idx] for x, x_idx in zip(args, x_idxes)]
        decomp_res_stack = f(*x_stacks, **kw)
        msg_extra = f'{x_idxes = }, {res_idx = }'
        assert_equal(res_stack, decomp_res_stack, msg_extra)
        if true_val:
            assert_equal(decomp_res_stack, true_val(*x_stacks), msg_extra)

def _test_namedtuple(res, fields, func_name):
    """
    Test that res is a namedtuple with the correct fields.
    """
    # isinstance(namedtuple) doesn't work, and it could be either
    # collections.namedtuple or typing.NamedTuple. So we just check that it is
    # a tuple subclass with the right fields in the right order.

    assert isinstance(res, tuple), f"{func_name}() did not return a tuple"
    assert type(res) != tuple, f"{func_name}() did not return a namedtuple"
    assert len(res) == len(fields), f"{func_name}() result tuple not the correct length (should have {len(fields)} elements)"
    for i, field in enumerate(fields):
        assert hasattr(res, field), f"{func_name}() result namedtuple doesn't have the '{field}' field"
        assert res[i] is getattr(res, field), f"{func_name}() result namedtuple '{field}' field is not in position {i}"

@pytest.mark.xp_extension('linalg')
@given(
    x=positive_definite_matrices(),
    kw=kwargs(upper=booleans())
)
def test_cholesky(x, kw):
    res = linalg.cholesky(x, **kw)

    assert res.shape == x.shape, "cholesky() did not return the correct shape"
    assert res.dtype == x.dtype, "cholesky() did not return the correct dtype"

    _test_stacks(linalg.cholesky, x, **kw, res=res)

    # Test that the result is upper or lower triangular
    if kw.get('upper', False):
        assert_exactly_equal(res, _array_module.triu(res))
    else:
        assert_exactly_equal(res, _array_module.tril(res))


@composite
def cross_args(draw, dtype_objects=dh.numeric_dtypes):
    """
    cross() requires two arrays with a size 3 in the 'axis' dimension

    To do this, we generate a shape and an axis but change the shape to be 3
    in the drawn axis.

    """
    shape = list(draw(shapes()))
    size = len(shape)
    assume(size > 0)

    kw = draw(kwargs(axis=integers(-size, size-1)))
    axis = kw.get('axis', -1)
    shape[axis] = 3
    shape = tuple(shape)

    mutual_dtypes = shared(mutually_promotable_dtypes(dtypes=dtype_objects))
    arrays1 = xps.arrays(
        dtype=mutual_dtypes.map(lambda pair: pair[0]),
        shape=shape,
    )
    arrays2 = xps.arrays(
        dtype=mutual_dtypes.map(lambda pair: pair[1]),
        shape=shape,
    )
    return draw(arrays1), draw(arrays2), kw

@pytest.mark.xp_extension('linalg')
@given(
    cross_args()
)
def test_cross(x1_x2_kw):
    x1, x2, kw = x1_x2_kw

    axis = kw.get('axis', -1)
    err = "test_cross produced invalid input. This indicates a bug in the test suite."
    assert x1.shape == x2.shape, err
    shape = x1.shape
    assert x1.shape[axis] == x2.shape[axis] == 3, err

    res = linalg.cross(x1, x2, **kw)

    assert res.dtype == dh.result_type(x1.dtype, x2.dtype), "cross() did not return the correct dtype"
    assert res.shape == shape, "cross() did not return the correct shape"

    def exact_cross(a, b):
        assert a.shape == b.shape == (3,), "Invalid cross() stack shapes. This indicates a bug in the test suite."
        return asarray([
            a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0],
        ], dtype=res.dtype)

    # We don't want to pass in **kw here because that would pass axis to
    # cross() on a single stack, but the axis is not meaningful on unstacked
    # vectors.
    _test_stacks(linalg.cross, x1, x2, dims=1, matrix_axes=(axis,), res=res, true_val=exact_cross)

@pytest.mark.xp_extension('linalg')
@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=square_matrix_shapes),
)
def test_det(x):
    res = linalg.det(x)

    assert res.dtype == x.dtype, "det() did not return the correct dtype"
    assert res.shape == x.shape[:-2], "det() did not return the correct shape"

    _test_stacks(linalg.det, x, res=res, dims=0)

    # TODO: Test that res actually corresponds to the determinant of x

@pytest.mark.xp_extension('linalg')
@given(
    x=xps.arrays(dtype=dtypes, shape=matrix_shapes()),
    # offset may produce an overflow if it is too large. Supporting offsets
    # that are way larger than the array shape isn't very important.
    kw=kwargs(offset=integers(-MAX_ARRAY_SIZE, MAX_ARRAY_SIZE))
)
def test_diagonal(x, kw):
    res = linalg.diagonal(x, **kw)

    assert res.dtype == x.dtype, "diagonal() returned the wrong dtype"

    n, m = x.shape[-2:]
    offset = kw.get('offset', 0)
    # Note: the spec does not specify that offset must be within the bounds of
    # the matrix. A large offset should just produce a size 0 in the last
    # dimension.
    if offset < 0:
        diag_size = min(n, m, max(n + offset, 0))
    elif offset == 0:
        diag_size = min(n, m)
    else:
        diag_size = min(n, m, max(m - offset, 0))

    assert res.shape == (*x.shape[:-2], diag_size), "diagonal() returned the wrong shape"

    def true_diag(x_stack):
        if offset >= 0:
            x_stack_diag = [x_stack[i, i + offset] for i in range(diag_size)]
        else:
            x_stack_diag = [x_stack[i - offset, i] for i in range(diag_size)]
        return asarray(x_stack_diag, dtype=x.dtype)

    _test_stacks(linalg.diagonal, x, **kw, res=res, dims=1, true_val=true_diag)

@pytest.mark.xp_extension('linalg')
@given(x=symmetric_matrices(finite=True))
def test_eigh(x):
    res = linalg.eigh(x)

    _test_namedtuple(res, ['eigenvalues', 'eigenvectors'], 'eigh')

    eigenvalues = res.eigenvalues
    eigenvectors = res.eigenvectors

    assert eigenvalues.dtype == x.dtype, "eigh().eigenvalues did not return the correct dtype"
    assert eigenvalues.shape == x.shape[:-1], "eigh().eigenvalues did not return the correct shape"

    assert eigenvectors.dtype == x.dtype, "eigh().eigenvectors did not return the correct dtype"
    assert eigenvectors.shape == x.shape, "eigh().eigenvectors did not return the correct shape"

    # Note: _test_stacks here is only testing the shape and dtype. The actual
    # eigenvalues and eigenvectors may not be equal at all, since there is not
    # requirements about how eigh computes an eigenbasis, or about the order
    # of the eigenvalues
    _test_stacks(lambda x: linalg.eigh(x).eigenvalues, x,
                 res=eigenvalues, dims=1)

    # TODO: Test that eigenvectors are orthonormal.

    _test_stacks(lambda x: linalg.eigh(x).eigenvectors, x,
                 res=eigenvectors, dims=2)

    # TODO: Test that res actually corresponds to the eigenvalues and
    # eigenvectors of x

@pytest.mark.xp_extension('linalg')
@given(x=symmetric_matrices(finite=True))
def test_eigvalsh(x):
    res = linalg.eigvalsh(x)

    assert res.dtype == x.dtype, "eigvalsh() did not return the correct dtype"
    assert res.shape == x.shape[:-1], "eigvalsh() did not return the correct shape"

    # Note: _test_stacks here is only testing the shape and dtype. The actual
    # eigenvalues may not be equal at all, since there is not requirements or
    # about the order of the eigenvalues, and the stacking code may use a
    # different code path.
    _test_stacks(linalg.eigvalsh, x, res=res, dims=1)

    # TODO: Should we test that the result is the same as eigh(x).eigenvalues?
    # (probably no because the spec doesn't actually require that)

    # TODO: Test that res actually corresponds to the eigenvalues of x

@pytest.mark.xp_extension('linalg')
@given(x=invertible_matrices())
def test_inv(x):
    res = linalg.inv(x)

    assert res.shape == x.shape, "inv() did not return the correct shape"
    assert res.dtype == x.dtype, "inv() did not return the correct dtype"

    _test_stacks(linalg.inv, x, res=res)

    # TODO: Test that the result is actually the inverse

@given(
    *two_mutual_arrays(dh.numeric_dtypes)
)
def test_matmul(x1, x2):
    # TODO: Make this also test the @ operator
    if (x1.shape == () or x2.shape == ()
        or len(x1.shape) == len(x2.shape) == 1 and x1.shape != x2.shape
        or len(x1.shape) == 1 and len(x2.shape) >= 2 and x1.shape[0] != x2.shape[-2]
        or len(x2.shape) == 1 and len(x1.shape) >= 2 and x2.shape[0] != x1.shape[-1]
        or len(x1.shape) >= 2 and len(x2.shape) >= 2 and x1.shape[-1] != x2.shape[-2]):
        # The spec doesn't specify what kind of exception is used here. Most
        # libraries will use a custom exception class.
        ph.raises(Exception, lambda: _array_module.matmul(x1, x2),
               "matmul did not raise an exception for invalid shapes")
        return
    else:
        res = _array_module.matmul(x1, x2)

    ph.assert_dtype("matmul", [x1.dtype, x2.dtype], res.dtype)

    if len(x1.shape) == len(x2.shape) == 1:
        assert res.shape == ()
    elif len(x1.shape) == 1:
        assert res.shape == x2.shape[:-2] + x2.shape[-1:]
        _test_stacks(_array_module.matmul, x1, x2, res=res, dims=1)
    elif len(x2.shape) == 1:
        assert res.shape == x1.shape[:-1]
        _test_stacks(_array_module.matmul, x1, x2, res=res, dims=1)
    else:
        stack_shape = sh.broadcast_shapes(x1.shape[:-2], x2.shape[:-2])
        assert res.shape == stack_shape + (x1.shape[-2], x2.shape[-1])
        _test_stacks(_array_module.matmul, x1, x2, res=res)

@pytest.mark.xp_extension('linalg')
@given(
    x=finite_matrices(),
    kw=kwargs(keepdims=booleans(),
              ord=sampled_from([-float('inf'), -2, -1, 1, 2, float('inf'), 'fro', 'nuc']))
)
def test_matrix_norm(x, kw):
    res = linalg.matrix_norm(x, **kw)

    keepdims = kw.get('keepdims', False)
    # TODO: Check that the ord values give the correct norms.
    # ord = kw.get('ord', 'fro')

    if keepdims:
        expected_shape = x.shape[:-2] + (1, 1)
    else:
        expected_shape = x.shape[:-2]
    assert res.shape == expected_shape, f"matrix_norm({keepdims=}) did not return the correct shape"
    assert res.dtype == x.dtype, "matrix_norm() did not return the correct dtype"

    _test_stacks(linalg.matrix_norm, x, **kw, dims=2 if keepdims else 0,
                 res=res)

matrix_power_n = shared(integers(-1000, 1000), key='matrix_power n')
@pytest.mark.xp_extension('linalg')
@given(
    # Generate any square matrix if n >= 0 but only invertible matrices if n < 0
    x=matrix_power_n.flatmap(lambda n: invertible_matrices() if n < 0 else
                             xps.arrays(dtype=xps.floating_dtypes(),
                                        shape=square_matrix_shapes)),
    n=matrix_power_n,
)
def test_matrix_power(x, n):
    res = linalg.matrix_power(x, n)

    assert res.shape == x.shape, "matrix_power() did not return the correct shape"
    assert res.dtype == x.dtype, "matrix_power() did not return the correct dtype"

    if n == 0:
        true_val = lambda x: _array_module.eye(x.shape[0], dtype=x.dtype)
    else:
        true_val = None
    # _test_stacks only works with array arguments
    func = lambda x: linalg.matrix_power(x, n)
    _test_stacks(func, x, res=res, true_val=true_val)

@pytest.mark.xp_extension('linalg')
@given(
    x=finite_matrices(shape=rtol_shared_matrix_shapes),
    kw=kwargs(rtol=rtols)
)
def test_matrix_rank(x, kw):
    linalg.matrix_rank(x, **kw)

@given(
    x=xps.arrays(dtype=dtypes, shape=matrix_shapes()),
)
def test_matrix_transpose(x):
    res = _array_module.matrix_transpose(x)
    true_val = lambda a: _array_module.asarray([[a[i, j] for i in
                                                range(a.shape[0])] for j in
                                                range(a.shape[1])],
                                               dtype=a.dtype)
    shape = list(x.shape)
    shape[-1], shape[-2] = shape[-2], shape[-1]
    shape = tuple(shape)
    assert res.shape == shape, "matrix_transpose() did not return the correct shape"
    assert res.dtype == x.dtype, "matrix_transpose() did not return the correct dtype"

    _test_stacks(_array_module.matrix_transpose, x, res=res, true_val=true_val)

@pytest.mark.xp_extension('linalg')
@given(
    *two_mutual_arrays(dtypes=dh.numeric_dtypes,
                       two_shapes=tuples(one_d_shapes, one_d_shapes))
)
def test_outer(x1, x2):
    # outer does not work on stacks. See
    # https://github.com/data-apis/array-api/issues/242.
    res = linalg.outer(x1, x2)

    shape = (x1.shape[0], x2.shape[0])
    assert res.shape == shape, "outer() did not return the correct shape"
    assert res.dtype == dh.result_type(x1.dtype, x2.dtype), "outer() did not return the correct dtype"

    if 0 in shape:
        true_res = _array_module.empty(shape, dtype=res.dtype)
    else:
        true_res = _array_module.asarray([[x1[i]*x2[j]
                                           for j in range(x2.shape[0])]
                                          for i in range(x1.shape[0])],
                                         dtype=res.dtype)

    assert_exactly_equal(res, true_res)

@pytest.mark.xp_extension('linalg')
@given(
    x=finite_matrices(shape=rtol_shared_matrix_shapes),
    kw=kwargs(rtol=rtols)
)
def test_pinv(x, kw):
    linalg.pinv(x, **kw)

@pytest.mark.xp_extension('linalg')
@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=matrix_shapes()),
    kw=kwargs(mode=sampled_from(['reduced', 'complete']))
)
def test_qr(x, kw):
    res = linalg.qr(x, **kw)
    mode = kw.get('mode', 'reduced')

    M, N = x.shape[-2:]
    K = min(M, N)

    _test_namedtuple(res, ['Q', 'R'], 'qr')
    Q = res.Q
    R = res.R

    assert Q.dtype == x.dtype, "qr().Q did not return the correct dtype"
    if mode == 'complete':
        assert Q.shape == x.shape[:-2] + (M, M), "qr().Q did not return the correct shape"
    else:
        assert Q.shape == x.shape[:-2] + (M, K), "qr().Q did not return the correct shape"

    assert R.dtype == x.dtype, "qr().R did not return the correct dtype"
    if mode == 'complete':
        assert R.shape == x.shape[:-2] + (M, N), "qr().R did not return the correct shape"
    else:
        assert R.shape == x.shape[:-2] + (K, N), "qr().R did not return the correct shape"

    _test_stacks(lambda x: linalg.qr(x, **kw).Q, x, res=Q)
    _test_stacks(lambda x: linalg.qr(x, **kw).R, x, res=R)

    # TODO: Test that Q is orthonormal

    # Check that R is upper-triangular.
    assert_exactly_equal(R, _array_module.triu(R))

@pytest.mark.xp_extension('linalg')
@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=square_matrix_shapes),
)
def test_slogdet(x):
    res = linalg.slogdet(x)

    _test_namedtuple(res, ['sign', 'logabsdet'], 'slotdet')

    sign, logabsdet = res

    assert sign.dtype == x.dtype, "slogdet().sign did not return the correct dtype"
    assert sign.shape == x.shape[:-2], "slogdet().sign did not return the correct shape"
    assert logabsdet.dtype == x.dtype, "slogdet().logabsdet did not return the correct dtype"
    assert logabsdet.shape == x.shape[:-2], "slogdet().logabsdet did not return the correct shape"


    _test_stacks(lambda x: linalg.slogdet(x).sign, x,
                 res=sign, dims=0)
    _test_stacks(lambda x: linalg.slogdet(x).logabsdet, x,
                 res=logabsdet, dims=0)

    # Check that when the determinant is 0, the sign and logabsdet are (0,
    # -inf).
    # TODO: This test does not necessarily hold exactly. Update it to test it
    # approximately.
    # d = linalg.det(x)
    # zero_det = equal(d, zero(d.shape, d.dtype))
    # assert_exactly_equal(sign[zero_det], zero(sign[zero_det].shape, x.dtype))
    # assert_exactly_equal(logabsdet[zero_det], -infinity(logabsdet[zero_det].shape, x.dtype))

    # More generally, det(x) should equal sign*exp(logabsdet), but this does
    # not hold exactly due to floating-point loss of precision.

    # TODO: Test this when we have tests for floating-point values.
    # assert all(abs(linalg.det(x) - sign*exp(logabsdet)) < eps)

def solve_args():
    """
    Strategy for the x1 and x2 arguments to test_solve()

    solve() takes x1, x2, where x1 is any stack of square invertible matrices
    of shape (..., M, M), and x2 is either shape (M,) or (..., M, K),
    where the ... parts of x1 and x2 are broadcast compatible.
    """
    stack_shapes = shared(two_mutually_broadcastable_shapes)
    # Don't worry about dtypes since all floating dtypes are type promotable
    # with each other.
    x1 = shared(invertible_matrices(stack_shapes=stack_shapes.map(lambda pair:
                                                                  pair[0])))

    @composite
    def _x2_shapes(draw):
        end = draw(integers(0, SQRT_MAX_ARRAY_SIZE))
        return draw(stack_shapes)[1] + draw(x1).shape[-1:] + (end,)

    x2_shapes = one_of(x1.map(lambda x: (x.shape[-1],)), _x2_shapes())
    x2 = xps.arrays(dtype=xps.floating_dtypes(), shape=x2_shapes)
    return x1, x2

@pytest.mark.xp_extension('linalg')
@given(*solve_args())
def test_solve(x1, x2):
    res = linalg.solve(x1, x2)

    # TODO: This requires an upstream fix to ndindex
    # (https://github.com/Quansight-Labs/ndindex/pull/131)

    # if x2.ndim == 1:
    #     _test_stacks(linalg.solve, x1, x2, res=res, dims=1)
    # else:
    #     _test_stacks(linalg.solve, x1, x2, res=res, dims=2)

@pytest.mark.xp_extension('linalg')
@given(
    x=finite_matrices(),
    kw=kwargs(full_matrices=booleans())
)
def test_svd(x, kw):
    res = linalg.svd(x, **kw)
    full_matrices = kw.get('full_matrices', True)

    *stack, M, N = x.shape
    K = min(M, N)

    _test_namedtuple(res, ['U', 'S', 'Vh'], 'svd')

    U, S, Vh = res

    assert U.dtype == x.dtype, "svd().U did not return the correct dtype"
    assert S.dtype == x.dtype, "svd().S did not return the correct dtype"
    assert Vh.dtype == x.dtype, "svd().Vh did not return the correct dtype"

    if full_matrices:
        assert U.shape == (*stack, M, M), "svd().U did not return the correct shape"
        assert Vh.shape == (*stack, N, N), "svd().Vh did not return the correct shape"
    else:
        assert U.shape == (*stack, M, K), "svd(full_matrices=False).U did not return the correct shape"
        assert Vh.shape == (*stack, K, N), "svd(full_matrices=False).Vh did not return the correct shape"
    assert S.shape == (*stack, K), "svd().S did not return the correct shape"

    # The values of s must be sorted from largest to smallest
    if K >= 1:
        assert _array_module.all(S[..., :-1] >= S[..., 1:]), "svd().S values are not sorted from largest to smallest"

    _test_stacks(lambda x: linalg.svd(x, **kw).U, x, res=U)
    _test_stacks(lambda x: linalg.svd(x, **kw).S, x, dims=1, res=S)
    _test_stacks(lambda x: linalg.svd(x, **kw).Vh, x, res=Vh)

@pytest.mark.xp_extension('linalg')
@given(
    x=finite_matrices(),
)
def test_svdvals(x):
    res = linalg.svdvals(x)

    *stack, M, N = x.shape
    K = min(M, N)

    assert res.dtype == x.dtype, "svdvals() did not return the correct dtype"
    assert res.shape == (*stack, K), "svdvals() did not return the correct shape"

    # SVD values must be sorted from largest to smallest
    assert _array_module.all(res[..., :-1] >= res[..., 1:]), "svdvals() values are not sorted from largest to smallest"

    _test_stacks(linalg.svdvals, x, dims=1, res=res)

    # TODO: Check that svdvals() is the same as svd().s.

_tensordot_pre_shapes = shared(two_mutually_broadcastable_shapes)

@composite
def _tensordot_axes(draw):
    shape1, shape2 = draw(_tensordot_pre_shapes)
    ndim1, ndim2 = len(shape1), len(shape2)
    isint = draw(booleans())

    if isint:
        N = min(ndim1, ndim2)
        return draw(integers(0, N))
    else:
        if ndim1 < ndim2:
            first = draw(xps.valid_tuple_axes(ndim1))
            second = draw(xps.valid_tuple_axes(ndim2, min_size=len(first),
                                               max_size=len(first)))
        else:
            second = draw(xps.valid_tuple_axes(ndim2))
            first = draw(xps.valid_tuple_axes(ndim1, min_size=len(second),
                                               max_size=len(second)))
        return (tuple(first), tuple(second))

tensordot_kw = shared(kwargs(axes=_tensordot_axes()))

@composite
def tensordot_shapes(draw):
    _shape1, _shape2 = map(list, draw(_tensordot_pre_shapes))
    ndim1, ndim2 = len(_shape1), len(_shape2)
    kw = draw(tensordot_kw)
    if 'axes' not in kw:
        assume(ndim1 >= 2 and ndim2 >= 2)
    axes = kw.get('axes', 2)

    if isinstance(axes, int):
        axes = [list(range(-axes, 0)), list(range(0, axes))]

    first, second = axes
    for i, j in zip(first, second):
        try:
            if -ndim2 <= j < ndim2 and _shape2[j] != 1:
                _shape1[i] = _shape2[j]
            if -ndim1 <= i < ndim1 and _shape1[i] != 1:
                _shape2[j] = _shape1[i]
        except:
            raise

    shape1, shape2 = map(tuple, [_shape1, _shape2])
    return (shape1, shape2)

def _test_tensordot_stacks(x1, x2, kw, res):
    """
    Variant of _test_stacks for tensordot

    tensordot doesn't stack directly along the non-contracted dimensions like
    the other linalg functions. Rather, it is stacked along the product of
    each non-contracted dimension. These dimensions are independent of one
    another and do not broadcast.
    """
    shape1, shape2 = x1.shape, x2.shape

    axes = kw.get('axes', 2)

    if isinstance(axes, int):
        res_axes = axes
        axes = [list(range(-axes, 0)), list(range(0, axes))]
    else:
        # Convert something like (0, 4, 2) into (0, 2, 1)
        res_axes = []
        for a, s in zip(axes, [shape1, shape2]):
            indices = [range(len(s))[i] for i in a]
            repl = dict(zip(sorted(indices), range(len(indices))))
            res_axes.append(tuple(repl[i] for i in indices))

    for ((i,), (j,)), (res_idx,) in zip(
            itertools.product(
                iter_indices(shape1, skip_axes=axes[0]),
                iter_indices(shape2, skip_axes=axes[1])),
            iter_indices(res.shape)):
        i, j, res_idx = i.raw, j.raw, res_idx.raw

        res_stack = res[res_idx]
        x1_stack = x1[i]
        x2_stack = x2[j]
        decomp_res_stack = xp.tensordot(x1_stack, x2_stack, axes=res_axes)
        assert_equal(res_stack, decomp_res_stack)

@given(
    *two_mutual_arrays(dh.numeric_dtypes, two_shapes=tensordot_shapes()),
    tensordot_kw,
)
def test_tensordot(x1, x2, kw):
    # TODO: vary shapes, vary contracted axes, test different axes arguments
    res = xp.tensordot(x1, x2, **kw)

    ph.assert_dtype("tensordot", [x1.dtype, x2.dtype], res.dtype)

    axes = _axes = kw.get('axes', 2)

    if isinstance(axes, int):
        _axes = [list(range(-axes, 0)), list(range(0, axes))]

    _shape1 = list(x1.shape)
    _shape2 = list(x2.shape)
    for i, j in zip(*_axes):
        _shape1[i] = _shape2[j] = None
    _shape1 = tuple([i for i in _shape1 if i is not None])
    _shape2 = tuple([i for i in _shape2 if i is not None])
    result_shape = _shape1 + _shape2
    ph.assert_result_shape('tensordot', [x1.shape, x2.shape], res.shape,
                           expected=result_shape)
    # TODO: assert stacking and elements
    _test_tensordot_stacks(x1, x2, kw, res)

@pytest.mark.xp_extension('linalg')
@given(
    x=xps.arrays(dtype=xps.numeric_dtypes(), shape=matrix_shapes()),
    # offset may produce an overflow if it is too large. Supporting offsets
    # that are way larger than the array shape isn't very important.
    kw=kwargs(offset=integers(-MAX_ARRAY_SIZE, MAX_ARRAY_SIZE))
)
def test_trace(x, kw):
    res = linalg.trace(x, **kw)

    # TODO: trace() should promote in some cases. See
    # https://github.com/data-apis/array-api/issues/202. See also the dtype
    # argument to sum() below.

    # assert res.dtype == x.dtype, "trace() returned the wrong dtype"

    n, m = x.shape[-2:]
    offset = kw.get('offset', 0)
    assert res.shape == x.shape[:-2], "trace() returned the wrong shape"

    def true_trace(x_stack):
        # Note: the spec does not specify that offset must be within the
        # bounds of the matrix. A large offset should just produce a size 0
        # diagonal in the last dimension (trace 0). See test_diagonal().
        if offset < 0:
            diag_size = min(n, m, max(n + offset, 0))
        elif offset == 0:
            diag_size = min(n, m)
        else:
            diag_size = min(n, m, max(m - offset, 0))

        if offset >= 0:
            x_stack_diag = [x_stack[i, i + offset] for i in range(diag_size)]
        else:
            x_stack_diag = [x_stack[i - offset, i] for i in range(diag_size)]
        return _array_module.sum(asarray(x_stack_diag, dtype=x.dtype), dtype=x.dtype)

    _test_stacks(linalg.trace, x, **kw, res=res, dims=0, true_val=true_trace)


@given(
    *two_mutual_arrays(dh.numeric_dtypes, mutually_broadcastable_shapes(2, min_dims=1)),
    kwargs(axis=integers()),
)
def test_vecdot(x1, x2, kw):
    # TODO: vary shapes, test different axis arguments
    broadcasted_shape = sh.broadcast_shapes(x1.shape, x2.shape)
    ndim = len(broadcasted_shape)
    axis = kw.get('axis', -1)
    if not (-ndim <= axis < ndim):
        ph.raises(Exception, lambda: xp.vecdot(x1, x2, **kw),
                  f"vecdot did not raise an exception for invalid axis ({ndim=}, {kw=})")
        return
    x1_shape = (1,)*(ndim - x1.ndim) + tuple(x1.shape)
    x2_shape = (1,)*(ndim - x2.ndim) + tuple(x2.shape)
    if x1_shape[axis] != x2_shape[axis]:
        ph.raises(Exception, lambda: xp.vecdot(x1, x2, **kw),
                  "vecdot did not raise an exception for invalid shapes")
        return
    expected_shape = list(broadcasted_shape)
    expected_shape.pop(axis)
    expected_shape = tuple(expected_shape)

    res = xp.vecdot(x1, x2, **kw)

    ph.assert_dtype("vecdot", [x1.dtype, x2.dtype], res.dtype)
    # TODO: assert shape and elements
    ph.assert_shape("vecdot", res.shape, expected_shape)

    if x1.dtype in dh.int_dtypes:
        def true_val(x, y, axix=-1):
            return xp.sum(x*y, dtype=res.dtype)
    else:
        true_val = None

    _test_stacks(linalg.vecdot, x1, x2, res=res, dims=0,
                 matrix_axes=(axis,), true_val=true_val)

# Insanely large orders might not work. There isn't a limit specified in the
# spec, so we just limit to reasonable values here.
max_ord = 100

@pytest.mark.xp_extension('linalg')
@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes(min_side=1)),
    data=data(),
)
def test_vector_norm(x, data):
    kw = data.draw(
        # We use data because axes is parameterized on x.ndim
        kwargs(axis=axes(x.ndim),
               keepdims=booleans(),
               ord=one_of(
                   sampled_from([2, 1, 0, -1, -2, float("inf"), float("-inf")]),
                   integers(-max_ord, max_ord),
                   floats(-max_ord, max_ord),
               )), label="kw")


    res = linalg.vector_norm(x, **kw)
    axis = kw.get('axis', None)
    keepdims = kw.get('keepdims', False)
    # TODO: Check that the ord values give the correct norms.
    # ord = kw.get('ord', 2)

    _axes = sh.normalise_axis(axis, x.ndim)

    ph.assert_keepdimable_shape('linalg.vector_norm', res.shape, x.shape,
                                _axes, keepdims, **kw)
    ph.assert_dtype('linalg.vector_norm', x.dtype, res.dtype)

    _kw = kw.copy()
    _kw.pop('axis', None)
    _test_stacks(linalg.vector_norm, x, res=res,
                 dims=x.ndim if keepdims else 0,
                 matrix_axes=_axes, **_kw
                 )
