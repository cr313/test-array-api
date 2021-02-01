from functools import reduce
from operator import mul
from math import sqrt

from hypothesis.strategies import (lists, integers, builds, sampled_from,
                                   shared, tuples as hypotheses_tuples,
                                   floats, just, composite, one_of, none,
                                   booleans)
from hypothesis import assume

from .pytest_helpers import nargs
from .array_helpers import dtype_ranges
from ._array_module import (_integer_dtypes, _floating_dtypes,
                            _numeric_dtypes, _boolean_dtypes, _dtypes, ones,
                            full, float32, float64, bool as bool_dtype)
from . import _array_module

from .function_stubs import elementwise_functions

integer_dtype_objects = [getattr(_array_module, t) for t in _integer_dtypes]
floating_dtype_objects = [getattr(_array_module, t) for t in _floating_dtypes]
numeric_dtype_objects = [getattr(_array_module, t) for t in _numeric_dtypes]
boolean_dtype_objects = [getattr(_array_module, t) for t in _boolean_dtypes]
dtype_objects = [getattr(_array_module, t) for t in _dtypes]

integer_dtypes = sampled_from(integer_dtype_objects)
floating_dtypes = sampled_from(floating_dtype_objects)
numeric_dtypes = sampled_from(numeric_dtype_objects)
integer_or_boolean_dtypes = sampled_from(integer_dtype_objects + boolean_dtype_objects)
boolean_dtypes = sampled_from(boolean_dtype_objects)
dtypes = sampled_from(dtype_objects)

shared_dtypes = shared(dtypes)

# shared() allows us to draw either the function or the function name and they
# will both correspond to the same function.

# TODO: Extend this to all functions, not just elementwise
elementwise_functions_names = shared(sampled_from(elementwise_functions.__all__))
array_functions_names = elementwise_functions_names
multiarg_array_functions_names = array_functions_names.filter(
    lambda func_name: nargs(func_name) > 1)

elementwise_function_objects = elementwise_functions_names.map(
    lambda i: getattr(_array_module, i))
array_functions = elementwise_function_objects
multiarg_array_functions = multiarg_array_functions_names.map(
    lambda i: getattr(_array_module, i))

# Limit the total size of an array shape
MAX_ARRAY_SIZE = 10000
# Size to use for 2-dim arrays
SQRT_MAX_ARRAY_SIZE = int(sqrt(MAX_ARRAY_SIZE))

# np.prod and others have overflow and math.prod is Python 3.8+ only
def prod(seq):
    return reduce(mul, seq, 1)

# hypotheses.strategies.tuples only generates tuples of a fixed size
def tuples(elements, *, min_size=0, max_size=None, unique_by=None, unique=False):
    return lists(elements, min_size=min_size, max_size=max_size,
                 unique_by=unique_by, unique=unique).map(tuple)

shapes = tuples(integers(0, 10)).filter(lambda shape: prod(shape) < MAX_ARRAY_SIZE)

# Use this to avoid memory errors with NumPy.
# See https://github.com/numpy/numpy/issues/15753

shapes = tuples(integers(0, 10)).filter(
             lambda shape: prod([i for i in shape if i]) < MAX_ARRAY_SIZE)

sizes = integers(0, MAX_ARRAY_SIZE)
sqrt_sizes = integers(0, SQRT_MAX_ARRAY_SIZE)

ones_arrays = builds(ones, shapes, dtype=shared_dtypes)

nonbroadcastable_ones_array_two_args = hypotheses_tuples(ones_arrays, ones_arrays)

# TODO: Generate general arrays here, rather than just scalars.
numeric_arrays = builds(full, just((1,)), floats())

@composite
def shared_scalars(draw):
    """
    Strategy to generate a scalar that matches the dtype from shared_dtypes
    """
    dtype = draw(shared_dtypes)
    if dtype in dtype_ranges:
        m, M = dtype_ranges[dtype]
        return draw(integers(m, M))
    elif dtype == bool_dtype:
        return draw(booleans())
    elif dtype == float64:
        return draw(floats())
    elif dtype == float32:
        return draw(floats(width=32))
    else:
        raise ValueError(f"Unrecognized dtype {dtype}")

@composite
def integer_indices(draw, sizes):
    size = draw(sizes)
    if size == 0:
        assume(False)
    return draw(integers(-size, size - 1))

@composite
def slices(draw, sizes):
    size = draw(sizes)
    # The spec does not specify out of bounds behavior.
    start = draw(one_of(integers(-size, max(0, size-1)), none()))
    stop = draw(one_of(integers(-size, size)), none())
    max_step_size = draw(integers(1, max(1, size)))
    step = draw(one_of(integers(-max_step_size, -1), integers(1, max_step_size), none()))
    s = slice(start, stop, step)
    l = list(range(size))
    sliced_list = l[s]
    if (sliced_list == []
        and size != 0
        and start is not None
        and stop is not None
        and stop != start
        ):
        # The spec does not specify behavior for out-of-bounds slices, except
        # for the case where stop == start.
        assume(False)
    return s

@composite
def multiaxis_indices(draw, shapes):
    res = []
    # Generate tuples no longer than the shape, with indices corresponding to
    # each dimension.
    shape = draw(shapes)
    guard = draw(tuples(just(object()), max_size=len(shape)))
    # from hypothesis import note
    # note(f"multiaxis_indices guard: {guard}")

    for size, _ in zip(shape, guard):
        res.append(draw(one_of(
            integer_indices(just(size)),
            slices(just(size)),
            just(...))))
    # Sometimes add more entries than necessary to test this.
    if len(guard) == len(shape) and ... not in res:
        # note("Adding extra")
        extra = draw(lists(one_of(integer_indices(sizes), slices(sizes)), min_size=0, max_size=3))
        res += extra
    return tuple(res)
