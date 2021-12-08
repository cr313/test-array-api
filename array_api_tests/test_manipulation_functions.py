import math
from collections import deque

from hypothesis import assume, given
from hypothesis import strategies as st

from . import _array_module as xp
from . import array_helpers as ah
from . import dtype_helpers as dh
from . import hypothesis_helpers as hh
from . import pytest_helpers as ph
from . import xps
from .typing import Shape


def shared_shapes(*args, **kwargs) -> st.SearchStrategy[Shape]:
    key = "shape"
    if args:
        key += " " + " ".join(args)
    if kwargs:
        key += " " + ph.fmt_kw(kwargs)
    return st.shared(hh.shapes(*args, **kwargs), key="shape")


@given(
    shape=hh.shapes(min_dims=1),
    dtypes=hh.mutually_promotable_dtypes(None, dtypes=dh.numeric_dtypes),
    kw=hh.kwargs(axis=st.just(0) | st.none()),  # TODO: test with axis >= 1
    data=st.data(),
)
def test_concat(shape, dtypes, kw, data):
    arrays = []
    for i, dtype in enumerate(dtypes, 1):
        x = data.draw(xps.arrays(dtype=dtype, shape=shape), label=f"x{i}")
        arrays.append(x)
    out = xp.concat(arrays, **kw)
    ph.assert_dtype("concat", dtypes, out.dtype)
    shapes = tuple(x.shape for x in arrays)
    if kw.get("axis", 0) == 0:
        pass  # TODO: assert expected shape
    elif kw["axis"] is None:
        size = sum(math.prod(s) for s in shapes)
        ph.assert_result_shape("concat", shapes, out.shape, (size,), **kw)
    # TODO: assert out elements match input arrays


@given(
    x=xps.arrays(dtype=xps.scalar_dtypes(), shape=shared_shapes()),
    axis=shared_shapes().flatmap(lambda s: st.integers(-len(s), len(s))),
)
def test_expand_dims(x, axis):
    out = xp.expand_dims(x, axis=axis)

    ph.assert_dtype("expand_dims", x.dtype, out.dtype)

    shape = [side for side in x.shape]
    index = axis if axis >= 0 else x.ndim + axis + 1
    shape.insert(index, 1)
    shape = tuple(shape)
    ph.assert_result_shape("expand_dims", (x.shape,), out.shape, shape)


@st.composite
def flip_axis(draw, shape):
    if len(shape) == 0 or draw(st.booleans()):
        return None
    else:
        ndim = len(shape)
        return draw(st.integers(-ndim, ndim - 1) | xps.valid_tuple_axes(ndim))


@given(
    x=xps.arrays(dtype=xps.scalar_dtypes(), shape=shared_shapes()),
    kw=hh.kwargs(axis=shared_shapes().flatmap(flip_axis)),
)
def test_flip(x, kw):
    out = xp.flip(x, **kw)

    ph.assert_dtype("expand_dims", x.dtype, out.dtype)

    # TODO: test all axis scenarios
    if kw.get("axis", None) is None:
        indices = list(ah.ndindex(x.shape))
        reverse_indices = indices[::-1]
        for x_idx, out_idx in zip(indices, reverse_indices):
            msg = f"out[{out_idx}]={out[out_idx]}, should be x[{x_idx}]={x[x_idx]}"
            if dh.is_float_dtype(x.dtype) and xp.isnan(x[x_idx]):
                assert xp.isnan(out[out_idx]), msg
            else:
                assert out[out_idx] == x[x_idx], msg


@given(
    x=xps.arrays(dtype=xps.scalar_dtypes(), shape=shared_shapes(min_dims=1)),
    axes=shared_shapes(min_dims=1).flatmap(
        lambda s: st.lists(
            st.integers(0, len(s) - 1),
            min_size=len(s),
            max_size=len(s),
            unique=True,
        ).map(tuple)
    ),
)
def test_permute_dims(x, axes):
    out = xp.permute_dims(x, axes)

    ph.assert_dtype("permute_dims", x.dtype, out.dtype)

    shape = [None for _ in range(len(axes))]
    for i, dim in enumerate(axes):
        side = x.shape[dim]
        shape[i] = side
    assert all(isinstance(side, int) for side in shape)  # sanity check
    shape = tuple(shape)
    ph.assert_result_shape("permute_dims", (x.shape,), out.shape, shape, axes=axes)

    # TODO: test elements


MAX_RESHAPE_SIDE = hh.MAX_ARRAY_SIZE // 64
reshape_x_shapes = st.shared(
    hh.shapes().filter(lambda s: math.prod(s) <= MAX_RESHAPE_SIDE),
    key="reshape x shape",
)


@st.composite
def reshape_shapes(draw, shape):
    size = 1 if len(shape) == 0 else math.prod(shape)
    rshape = draw(st.lists(st.integers(0)).filter(lambda s: math.prod(s) == size))
    assume(all(side <= MAX_RESHAPE_SIDE for side in rshape))
    if len(rshape) != 0 and size > 0 and draw(st.booleans()):
        index = draw(st.integers(0, len(rshape) - 1))
        rshape[index] = -1
    return tuple(rshape)


@given(
    x=xps.arrays(dtype=xps.scalar_dtypes(), shape=reshape_x_shapes),
    shape=reshape_x_shapes.flatmap(reshape_shapes),
)
def test_reshape(x, shape):
    assume(math.prod(shape) == math.prod(x.shape))

    out = xp.reshape(x, shape)

    ph.assert_dtype("reshape", x.dtype, out.dtype)

    _shape = shape
    if any(side == -1 for side in shape):
        size = math.prod(x.shape)
        rsize = math.prod(shape) * -1
        _shape[shape.index(-1)] = size / rsize
    ph.assert_result_shape("reshape", (x.shape,), out.shape, _shape, shape=shape)

    for x_idx, out_idx in zip(ah.ndindex(x.shape), ah.ndindex(out.shape)):
        msg = f"out[{out_idx}]={out[out_idx]}, should be x[{x_idx}]={x[x_idx]}"
        if dh.is_float_dtype(x.dtype) and xp.isnan(x[x_idx]):
            assert xp.isnan(out[out_idx]), msg
        else:
            assert out[out_idx] == x[x_idx], msg


@given(xps.arrays(dtype=xps.scalar_dtypes(), shape=shared_shapes()), st.data())
def test_roll(x, data):
    shift = data.draw(
        st.integers() | st.lists(st.integers(), max_size=x.ndim).map(tuple),
        label="shift",
    )
    axis_strats = [st.none()]
    if x.shape != ():
        axis_strats.append(st.integers(-x.ndim, x.ndim - 1))
        if isinstance(shift, int):
            axis_strats.append(xps.valid_tuple_axes(x.ndim))
    kw = data.draw(hh.kwargs(axis=st.one_of(axis_strats)), label="kw")

    out = xp.roll(x, shift, **kw)

    ph.assert_dtype("roll", x.dtype, out.dtype)

    ph.assert_result_shape("roll", (x.shape,), out.shape)

    # TODO: test all shift/axis scenarios
    if isinstance(shift, int) and kw.get("axis", None) is None:
        indices = list(ah.ndindex(x.shape))
        shifted_indices = deque(indices)
        shifted_indices.rotate(shift)
        for x_idx, out_idx in zip(indices, shifted_indices):
            msg = f"out[{out_idx}]={out[out_idx]}, should be x[{x_idx}]={x[x_idx]}"
            if dh.is_float_dtype(x.dtype) and xp.isnan(x[x_idx]):
                assert xp.isnan(out[out_idx]), msg
            else:
                assert out[out_idx] == x[x_idx], msg


@given(
    x=xps.arrays(dtype=xps.scalar_dtypes(), shape=shared_shapes()),
    axis=shared_shapes().flatmap(
        lambda s: st.just(0)
        if len(s) == 0
        else st.integers(-len(s) + 1, len(s) - 1).filter(lambda i: s[i] == 1)
    ),  # TODO: tuple of axis i.e. axes
)
def test_squeeze(x, axis):
    xp.squeeze(x, axis)
    # TODO


@given(
    shape=hh.shapes(),
    dtypes=hh.mutually_promotable_dtypes(None),
    data=st.data(),
)
def test_stack(shape, dtypes, data):
    arrays = []
    for i, dtype in enumerate(dtypes, 1):
        x = data.draw(xps.arrays(dtype=dtype, shape=shape), label=f"x{i}")
        arrays.append(x)
    out = xp.stack(arrays)
    ph.assert_dtype("stack", dtypes, out.dtype)
    # TODO
