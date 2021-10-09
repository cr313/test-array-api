"""
Tests for linalg functions

https://data-apis.org/array-api/latest/API_specification/linear_algebra_functions.html

and

https://data-apis.org/array-api/latest/extensions/linear_algebra_functions.html

Note: this file currently mixes both the required linear algebra functions and
functions from the linalg extension. The functions in the latter are not
required, but we don't yet have a clean way to disable only those tests (see https://github.com/data-apis/array-api-tests/issues/25).

"""

from hypothesis import assume, given
from hypothesis.strategies import booleans, composite, none, integers, shared

from .array_helpers import (assert_exactly_equal, ndindex, asarray,
                            numeric_dtype_objects)
from .hypothesis_helpers import (xps, dtypes, shapes, kwargs, matrix_shapes,
                                 square_matrix_shapes, symmetric_matrices,
                                 positive_definite_matrices, MAX_ARRAY_SIZE,
                                 invertible_matrices, two_mutual_arrays,
                                 mutually_promotable_dtypes)
from .pytest_helpers import raises

from .test_broadcasting import broadcast_shapes

from . import _array_module

# Standin strategy for not yet implemented tests
todo = none()

def _test_stacks(f, *args, res=None, dims=2, true_val=None, **kw):
    """
    Test that f(*args, **kw) maps across stacks of matrices

    dims is the number of dimensions f should have for a single n x m matrix
    stack.

    true_val may be a function such that true_val(*x_stacks) gives the true
    value for f on a stack
    """
    if res is None:
        res = f(*args, **kw)

    shape = args[0].shape if len(args) == 1 else broadcast_shapes(*[x.shape
                                                                    for x in args])
    for _idx in ndindex(shape[:-2]):
        idx = _idx + (slice(None),)*dims
        res_stack = res[idx]
        x_stacks = [x[idx] for x in args]
        decomp_res_stack = f(*x_stacks, **kw)
        assert_exactly_equal(res_stack, decomp_res_stack)
        if true_val:
            assert_exactly_equal(decomp_res_stack, true_val(*x_stacks))

def _test_namedtuple(res, fields, func_name):
    """
    Test that res is a namedtuple with the correct fields.
    """
    # isinstance(namedtuple) doesn't work, and it could be either
    # collections.namedtuple or typing.NamedTuple. So we just check that it is
    # a tuple subclass with the right fields in the right order.

    assert isinstance(res, tuple), f"{func_name}() did not return a tuple"
    assert len(res) == len(fields), f"{func_name}() result tuple not the correct length (should have {len(fields)} elements)"
    for i, field in enumerate(fields):
        assert hasattr(res, field), f"{func_name}() result namedtuple doesn't have the '{field}' field"
        assert res[i] is getattr(res, field), f"{func_name}() result namedtuple '{field}' field is not in position {i}"

@given(
    x=positive_definite_matrices(),
    kw=kwargs(upper=booleans())
)
def test_cholesky(x, kw):
    res = _array_module.linalg.cholesky(x, **kw)

    assert res.shape == x.shape, "cholesky() did not return the correct shape"
    assert res.dtype == x.dtype, "cholesky() did not return the correct dtype"

    _test_stacks(_array_module.linalg.cholesky, x, **kw, res=res)

    # Test that the result is upper or lower triangular
    if kw.get('upper', False):
        assert_exactly_equal(res, _array_module.triu(res))
    else:
        assert_exactly_equal(res, _array_module.tril(res))


@composite
def cross_args(draw, dtype_objects=numeric_dtype_objects):
    """
    cross() requires two arrays with a size 3 in the 'axis' dimension

    To do this, we generate a shape and an axis but change the shape to be 3
    in the drawn axis.

    """
    shape = list(draw(shapes))
    size = len(shape)
    assume(size > 0)

    kw = draw(kwargs(axis=integers(-size, size-1)))
    axis = kw.get('axis', -1)
    shape[axis] = 3

    mutual_dtypes = shared(mutually_promotable_dtypes(dtype_objects))
    arrays1 = xps.arrays(
        dtype=mutual_dtypes.map(lambda pair: pair[0]),
        shape=shape,
    )
    arrays2 = xps.arrays(
        dtype=mutual_dtypes.map(lambda pair: pair[1]),
        shape=shape,
    )
    return draw(arrays1), draw(arrays2), kw

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

    res = _array_module.linalg.cross(x1, x2, **kw)

    # TODO: Replace result_type() with a helper function
    assert res.dtype == _array_module.result_type(x1, x2), "cross() did not return the correct dtype"
    assert res.shape == shape, "cross() did not return the correct shape"

    # cross is too different from other functions to use _test_stacks, and it
    # is the only function that works the way it does, so it's not really
    # worth generalizing _test_stacks to handle it.
    a = axis if axis >= 0 else axis + len(shape)
    for _idx in ndindex(shape[:a] + shape[a+1:]):
        idx = _idx[:a] + (slice(None),) + _idx[a:]
        assert len(idx) == len(shape), "Invalid index. This indicates a bug in the test suite."
        res_stack = res[idx]
        x1_stack = x1[idx]
        x2_stack = x2[idx]
        assert x1_stack.shape == x2_stack.shape == (3,), "Invalid cross() stack shapes. This indicates a bug in the test suite."
        decomp_res_stack = _array_module.linalg.cross(x1_stack, x2_stack)
        assert_exactly_equal(res_stack, decomp_res_stack)

        exact_cross = asarray([
            x1_stack[1]*x2_stack[2] - x1_stack[2]*x2_stack[1],
            x1_stack[2]*x2_stack[0] - x1_stack[0]*x2_stack[2],
            x1_stack[0]*x2_stack[1] - x1_stack[1]*x2_stack[0],
            ], dtype=res.dtype)
        assert_exactly_equal(res_stack, exact_cross)

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=square_matrix_shapes),
)
def test_det(x):
    res = _array_module.linalg.det(x)

    assert res.dtype == x.dtype, "det() did not return the correct dtype"
    assert res.shape == x.shape[:-2], "det() did not return the correct shape"

    _test_stacks(_array_module.linalg.det, x, res=res, dims=0)

    # TODO: Test that res actually corresponds to the determinant of x

@given(
    x=xps.arrays(dtype=dtypes, shape=matrix_shapes),
    # offset may produce an overflow if it is too large. Supporting offsets
    # that are way larger than the array shape isn't very important.
    kw=kwargs(offset=integers(-MAX_ARRAY_SIZE, MAX_ARRAY_SIZE))
)
def test_diagonal(x, kw):
    res = _array_module.linalg.diagonal(x, **kw)

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

    _test_stacks(_array_module.linalg.diagonal, x, **kw, res=res, dims=1, true_val=true_diag)

@given(x=symmetric_matrices(finite=True))
def test_eigh(x):
    res = _array_module.linalg.eigh(x)

    _test_namedtuple(res, ['eigenvalues', 'eigenvectors'], 'eigh')

    eigenvalues = res.eigenvalues
    eigenvectors = res.eigenvectors

    assert eigenvalues.dtype == x.dtype, "eigh().eigenvalues did not return the correct dtype"
    assert eigenvalues.shape == x.shape[:-1], "eigh().eigenvalues did not return the correct shape"

    assert eigenvectors.dtype == x.dtype, "eigh().eigenvectors did not return the correct dtype"
    assert eigenvectors.shape == x.shape, "eigh().eigenvectors did not return the correct shape"

    _test_stacks(lambda x: _array_module.linalg.eigh(x).eigenvalues, x,
                 res=eigenvalues, dims=1)
    _test_stacks(lambda x: _array_module.linalg.eigh(x).eigenvectors, x,
                 res=eigenvectors, dims=2)

    # TODO: Test that res actually corresponds to the eigenvalues and
    # eigenvectors of x

@given(x=symmetric_matrices(finite=True))
def test_eigvalsh(x):
    res = _array_module.linalg.eigvalsh(x)

    assert res.dtype == x.dtype, "eigvalsh() did not return the correct dtype"
    assert res.shape == x.shape[:-1], "eigvalsh() did not return the correct shape"

    _test_stacks(_array_module.linalg.eigvalsh, x, res=res, dims=1)

    # TODO: Should we test that the result is the same as eigh(x).eigenvalues?

    # TODO: Test that res actually corresponds to the eigenvalues of x

@given(x=invertible_matrices())
def test_inv(x):
    res = _array_module.linalg.inv(x)

    assert res.shape == x.shape, "inv() did not return the correct shape"
    assert res.dtype == x.dtype, "inv() did not return the correct dtype"

    _test_stacks(_array_module.linalg.inv, x, res=res)

    # TODO: Test that the result is actually the inverse

@given(
    *two_mutual_arrays(numeric_dtype_objects)
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
        raises(Exception, lambda: _array_module.linalg.matmul(x1, x2),
               "matmul did not raise an exception for invalid shapes")
        return
    else:
        res = _array_module.linalg.matmul(x1, x2)

    # TODO: Replace result_type() with a helper function
    assert res.dtype == _array_module.result_type(x1, x2), "matmul() did not return the correct dtype"

    if len(x1.shape) == len(x2.shape) == 1:
        assert res.shape == ()
    elif len(x1.shape) == 1:
        assert res.shape == x2.shape[:-2] + x2.shape[-1:]
        _test_stacks(_array_module.linalg.matmul, x1, x2, res=res, dims=1)
    elif len(x2.shape) == 1:
        assert res.shape == x1.shape[:-1]
        _test_stacks(_array_module.linalg.matmul, x1, x2, res=res, dims=1)
    else:
        stack_shape = broadcast_shapes(x1.shape[:-2], x2.shape[:-2])
        assert res.shape == stack_shape + (x1.shape[-2], x2.shape[-1])
        _test_stacks(_array_module.linalg.matmul, x1, x2, res=res)

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(axis=todo, keepdims=todo, ord=todo)
)
def test_matrix_norm(x, kw):
    # res = _array_module.linalg.matrix_norm(x, **kw)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    n=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
)
def test_matrix_power(x, n):
    # res = _array_module.linalg.matrix_power(x, n)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(rtol=todo)
)
def test_matrix_rank(x, kw):
    # res = _array_module.linalg.matrix_rank(x, **kw)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
)
def test_matrix_transpose(x):
    # res = _array_module.linalg.matrix_transpose(x)
    pass

@given(
    x1=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    x2=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
)
def test_outer(x1, x2):
    # res = _array_module.linalg.outer(x1, x2)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(rtol=todo)
)
def test_pinv(x, kw):
    # res = _array_module.linalg.pinv(x, **kw)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(mode=todo)
)
def test_qr(x, kw):
    # res = _array_module.linalg.qr(x, **kw)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
)
def test_slogdet(x):
    # res = _array_module.linalg.slogdet(x)
    pass

@given(
    x1=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    x2=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
)
def test_solve(x1, x2):
    # res = _array_module.linalg.solve(x1, x2)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(full_matrices=todo)
)
def test_svd(x, kw):
    # res = _array_module.linalg.svd(x, **kw)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
)
def test_svdvals(x):
    # res = _array_module.linalg.svdvals(x)
    pass

@given(
    x1=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    x2=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(axes=todo)
)
def test_tensordot(x1, x2, kw):
    # res = _array_module.linalg.tensordot(x1, x2, **kw)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(offset=todo)
)
def test_trace(x, kw):
    # res = _array_module.linalg.trace(x, **kw)
    pass

@given(
    x1=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    x2=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(axis=todo)
)
def test_vecdot(x1, x2, kw):
    # res = _array_module.linalg.vecdot(x1, x2, **kw)
    pass

@given(
    x=xps.arrays(dtype=xps.floating_dtypes(), shape=shapes),
    kw=kwargs(axis=todo, keepdims=todo, ord=todo)
)
def test_vector_norm(x, kw):
    # res = _array_module.linalg.vector_norm(x, **kw)
    pass
