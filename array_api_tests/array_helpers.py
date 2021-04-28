from ._array_module import (isnan, all, any, equal, not_equal, logical_and,
                            logical_or, isfinite, greater, less, less_equal,
                            zeros, ones, full, bool, int8, int16, int32,
                            int64, uint8, uint16, uint32, uint64, float32,
                            float64, nan, inf, pi, remainder, divide, isinf,
                            negative, _integer_dtypes, _floating_dtypes,
                            _numeric_dtypes, _boolean_dtypes, _dtypes, )
from . import _array_module

# These are exported here so that they can be included in the special cases
# tests from this file.
from ._array_module import logical_not, subtract, floor, ceil, where

__all__ = ['all', 'any', 'logical_and', 'logical_or', 'logical_not', 'less',
           'greater', 'subtract', 'negative', 'floor', 'ceil', 'where',
           'isfinite', 'equal', 'not_equal', 'zero', 'one', 'NaN', 'infinity',
           'π', 'isnegzero', 'non_zero', 'isposzero', 'exactly_equal',
           'assert_exactly_equal', 'notequal', 'assert_finite',
           'assert_non_zero', 'ispositive', 'assert_positive', 'isnegative',
           'assert_negative', 'isintegral', 'assert_integral', 'isodd',
           'iseven', "assert_iseven", 'assert_isinf',
           'positive_mathematical_sign', 'assert_positive_mathematical_sign',
           'negative_mathematical_sign', 'assert_negative_mathematical_sign',
           'same_sign', 'assert_same_sign']

def zero(shape, dtype):
    """
    Returns a scalar 0 of the given dtype.

    This should be used in place of the literal "0" in the test suite, as the
    spec does not require any behavior with Python literals (and in
    particular, it does not specify how the integer 0 and the float 0.0 work
    with type promotion).

    To get -0, use -zero(dtype) (note that -0 is only defined for floating
    point dtypes).
    """
    return zeros(shape, dtype=dtype)

def one(shape, dtype):
    """
    Returns a scalar 1 of the given dtype.

    This should be used in place of the literal "1" in the test suite, as the
    spec does not require any behavior with Python literals (and in
    particular, it does not specify how the integer 1 and the float 1.0 work
    with type promotion).

    To get -1, use -one(dtype).
    """
    return ones(shape, dtype=dtype)

def NaN(shape, dtype):
    """
    Returns a scalar nan of the given dtype.

    Note that this is only defined for floating point dtypes.
    """
    if dtype not in [float32, float64]:
        raise RuntimeError(f"Unexpected dtype {dtype} in NaN().")
    return full(shape, nan, dtype=dtype)

def infinity(shape, dtype):
    """
    Returns a scalar positive infinity of the given dtype.

    Note that this is only defined for floating point dtypes.

    To get negative infinity, use -infinity(dtype).

    """
    if dtype not in [float32, float64]:
        raise RuntimeError(f"Unexpected dtype {dtype} in infinity().")
    return full(shape, inf, dtype=dtype)

def π(shape, dtype):
    """
    Returns a scalar π.

    Note that this function is only defined for floating point dtype.

    To get rational multiples of π, use, e.g., 3*π(dtype)/2.

    """
    if dtype not in [float32, float64]:
        raise RuntimeError(f"Unexpected dtype {dtype} in π().")
    return full(shape, pi, dtype=dtype)

def isnegzero(x):
    """
    Returns a mask where x is -0.
    """
    # TODO: If copysign or signbit are added to the spec, use those instead.
    shape = x.shape
    dtype = x.dtype
    return equal(divide(one(shape, dtype), x), -infinity(shape, dtype))

def isposzero(x):
    """
    Returns a mask where x is +0 (but not -0).
    """
    # TODO: If copysign or signbit are added to the spec, use those instead.
    shape = x.shape
    dtype = x.dtype
    return equal(divide(one(shape, dtype), x), infinity(shape, dtype))

def exactly_equal(x, y):
    """
    Same as equal(x, y) except it gives True where both values are nan, and
    distinguishes +0 and -0.

    This function implicitly assumes x and y have the same shape and dtype.
    """
    if x.dtype in [float32, float64]:
        xnegzero = isnegzero(x)
        ynegzero = isnegzero(y)

        xposzero = isposzero(x)
        yposzero = isposzero(y)

        xnan = isnan(x)
        ynan = isnan(y)

        # (x == y OR x == y == NaN) AND xnegzero == ynegzero AND xposzero == y poszero
        return logical_and(logical_and(
            logical_or(equal(x, y), logical_and(xnan, ynan)),
            equal(xnegzero, ynegzero)),
            equal(xposzero, yposzero))

    return equal(x, y)

def notequal(x, y):
    """
    Same as not_equal(x, y) except it gives False when both values are nan.

    Note: this function does NOT distinguish +0 and -0.

    This function implicitly assumes x and y have the same shape and dtype.
    """
    if x.dtype in [float32, float64]:
        xnan = isnan(x)
        ynan = isnan(y)

        both_nan = logical_and(xnan, ynan)
        # NOT both nan AND (both nan OR x != y)
        return logical_and(logical_not(both_nan), not_equal(x, y))

    return not_equal(x, y)

def assert_exactly_equal(x, y):
    """
    Test that the arrays x and y are exactly equal.

    If x and y do not have the same shape and dtype, they are not considered
    equal.

    """
    assert x.shape == y.shape, f"The input arrays do not have the same shapes ({x.shape} != {y.shape})"

    assert x.dtype == y.dtype, f"The input arrays do not have the same dtype ({x.dtype} != {y.dtype})"

    assert all(exactly_equal(x, y)), "The input arrays have different values"

def assert_finite(x):
    """
    Test that the array x is finite
    """
    assert all(isfinite(x)), "The input array is not finite"

def non_zero(x):
    return not_equal(x, zero(x.shape, x.dtype))

def assert_non_zero(x):
    assert all(non_zero(x)), "The input array is not nonzero"

def ispositive(x):
    return greater(x, zero(x.shape, x.dtype))

def assert_positive(x):
    assert all(ispositive(x)), "The input array is not positive"

def isnegative(x):
    return less(x, zero(x.shape, x.dtype))

def assert_negative(x):
    assert all(isnegative(x)), "The input array is not negative"

def inrange(x, a, b, epsilon=0):
    """
    Returns a mask for values of x in the range [a-epsilon, a+epsilon], inclusive

    """
    A = full(x.shape, a, dtype=x.dtype)
    B = full(x.shape, b, dtype=x.dtype)
    eps = full(x.shape, epsilon, dtype=x.dtype)
    return logical_and(less_equal(A-eps, x), less_equal(x, B+eps))

def isintegral(x):
    """
    Returns a mask the shape of x where the values are integral

    x is integral if its dtype is an integer dtype, or if it is a floating
    point value that can be exactly represented as an integer.
    """
    if x.dtype in [int8, int16, int32, int64, uint8, uint16, uint32, uint64]:
        return full(x.shape, True, dtype=bool)
    elif x.dtype in [float32, float64]:
        return equal(remainder(x, one(x.shape, x.dtype)), zero(x.shape, x.dtype))
    else:
        return full(x.shape, False, dtype=bool)

def assert_integral(x):
    """
    Check that x has only integer values
    """
    assert all(isintegral(x)), "The input array has nonintegral values"

def isodd(x):
    return logical_and(
        isintegral(x),
        equal(
            remainder(x, 2*one(x.shape, x.dtype)),
            one(x.shape, x.dtype)))

def iseven(x):
    return logical_and(
        isintegral(x),
        equal(
            remainder(x, 2*one(x.shape, x.dtype)),
            zero(x.shape, x.dtype)))

def assert_iseven(x):
    """
    Check that x is an even integer
    """
    assert all(iseven(x)), "The input array is not even"

def assert_isinf(x):
    """
    Check that x is an infinity
    """
    assert all(isinf(x)), "The input array is not infinite"

def positive_mathematical_sign(x):
    """
    Check if x has a positive "mathematical sign"

    The "mathematical sign" here means the sign bit is 0. This includes 0,
    positive finite numbers, and positive infinity. It does not include any
    nans, as signed nans are not required by the spec.

    """
    return logical_or(greater(x, 0), isposzero(x))

def assert_positive_mathematical_sign(x):
    assert all(positive_mathematical_sign(x)), "The input arrays do not have a positive mathematical sign"

def negative_mathematical_sign(x):
    """
    Check if x has a negative "mathematical sign"

    The "mathematical sign" here means the sign bit is 1. This includes -0,
    negative finite numbers, and negative infinity. It does not include any
    nans, as signed nans are not required by the spec.

    """
    if x.dtype in [float32, float64]:
        return logical_or(less(x, 0), isnegzero(x))
    return less(x, 0)

def assert_negative_mathematical_sign(x):
    assert all(negative_mathematical_sign(x)), "The input arrays do not have a negative mathematical sign"

def same_sign(x, y):
    """
    Check if x and y have the "same sign"

    x and y have the same sign if they are both nonnegative or both negative.
    For the purposes of this function 0 and 1 have the same sign and -0 and -1
    have the same sign. The value of this function is False if either x or y
    is nan, as signed nans are not required by the spec.
    """
    return logical_or(
        logical_and(positive_mathematical_sign(x), positive_mathematical_sign(y)),
        logical_and(negative_mathematical_sign(x), negative_mathematical_sign(y)))

def assert_same_sign(x, y):
    assert all(same_sign(x, y)), "The input arrays do not have the same sign"


integer_dtype_objects = [getattr(_array_module, t) for t in _integer_dtypes]
floating_dtype_objects = [getattr(_array_module, t) for t in _floating_dtypes]
numeric_dtype_objects = [getattr(_array_module, t) for t in _numeric_dtypes]
boolean_dtype_objects = [getattr(_array_module, t) for t in _boolean_dtypes]
integer_or_boolean_dtype_objects = integer_dtype_objects + boolean_dtype_objects
dtype_objects = [getattr(_array_module, t) for t in _dtypes]

def is_integer_dtype(dtype):
    if dtype is None:
        return False
    return dtype in [int8, int16, int32, int16, uint8, uint16, uint32, uint64]

def is_float_dtype(dtype):
    if dtype is None:
        # numpy.dtype('float64') == True gives True
        return False
    # TODO: Return True even for floating point dtypes that aren't part of the
    # spec, like np.float16
    return dtype in [float32, float64]

dtype_ranges = {
    int8: [-128, +127],
    int16: [-32_768, +32_767],
    int32: [-2_147_483_648, +2_147_483_647],
    int64: [-9_223_372_036_854_775_808, +9_223_372_036_854_775_807],
    uint8: [0, +255],
    uint16: [0, +65_535],
    uint32: [0, +4_294_967_295],
    uint64: [0, +18_446_744_073_709_551_615],
}

def int_to_dtype(x, n, signed):
    """
    Convert the Python integer x into an n bit signed or unsigned number.
    """
    mask = (1 << n) - 1
    x &= mask
    if signed:
        highest_bit = 1 << (n-1)
        if x & highest_bit:
            x = -((~x & mask) + 1)
    return x
