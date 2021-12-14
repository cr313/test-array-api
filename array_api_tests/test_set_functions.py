# TODO: disable if opted out
import math
from collections import Counter

from hypothesis import assume, given

from . import _array_module as xp
from . import array_helpers as ah
from . import dtype_helpers as dh
from . import hypothesis_helpers as hh
from . import pytest_helpers as ph
from . import xps
from .test_searching_functions import assert_default_index


@given(xps.arrays(dtype=xps.scalar_dtypes(), shape=hh.shapes()))
def test_unique_all(x):
    xp.unique_all(x)
    # TODO


@given(xps.arrays(dtype=xps.scalar_dtypes(), shape=hh.shapes(min_side=1)))
def test_unique_counts(x):
    out = xp.unique_counts(x)
    assert hasattr(out, "values")
    assert hasattr(out, "counts")
    ph.assert_dtype(
        "unique_counts", x.dtype, out.values.dtype, repr_name="out.values.dtype"
    )
    assert_default_index(
        "unique_counts", out.counts.dtype, repr_name="out.counts.dtype"
    )
    assert (
        out.counts.shape == out.values.shape
    ), f"{out.counts.shape=}, but should be {out.values.shape=}"
    scalar_type = dh.get_scalar_type(out.values.dtype)
    counts = Counter(scalar_type(x[idx]) for idx in ah.ndindex(x.shape))
    vals_idx = {}
    nans = 0
    for idx in ah.ndindex(out.values.shape):
        val = scalar_type(out.values[idx])
        count = int(out.counts[idx])
        if math.isnan(val):
            nans += 1
            assert count == 1, (
                f"out.counts[{idx}]={count} for out.values[{idx}]={val}, "
                "but count should be 1 as NaNs are distinct"
            )
        else:
            expected = counts[val]
            assert (
                expected > 0
            ), f"out.values[{idx}]={val}, but {val} not in input array"
            count = int(out.counts[idx])
            assert count == expected, (
                f"out.counts[{idx}]={count} for out.values[{idx}]={val}, "
                f"but should be {expected}"
            )
            assert (
                val not in vals_idx.keys()
            ), f"out[{idx}]={val}, but {val} is also in out[{vals_idx[val]}]"
            vals_idx[val] = idx
    if dh.is_float_dtype(out.values.dtype):
        assume(x.size <= 128)  # may not be representable
        expected = sum(v for k, v in counts.items() if math.isnan(k))
        assert nans == expected, f"{nans} NaNs in out, but should be {expected}"


@given(xps.arrays(dtype=xps.scalar_dtypes(), shape=hh.shapes(min_side=1)))
def test_unique_inverse(x):
    out = xp.unique_inverse(x)
    assert hasattr(out, "values")
    assert hasattr(out, "inverse_indices")
    ph.assert_dtype(
        "unique_inverse", x.dtype, out.values.dtype, repr_name="out.values.dtype"
    )
    assert_default_index(
        "unique_inverse",
        out.inverse_indices.dtype,
        repr_name="out.inverse_indices.dtype",
    )
    ph.assert_shape(
        "unique_inverse",
        out.inverse_indices.shape,
        x.shape,
        repr_name="out.inverse_indices.shape",
    )
    scalar_type = dh.get_scalar_type(out.values.dtype)
    distinct = set(scalar_type(x[idx]) for idx in ah.ndindex(x.shape))
    vals_idx = {}
    nans = 0
    for idx in ah.ndindex(out.values.shape):
        val = scalar_type(out.values[idx])
        if math.isnan(val):
            nans += 1
        else:
            assert (
                val in distinct
            ), f"out.values[{idx}]={val}, but {val} not in input array"
            assert (
                val not in vals_idx.keys()
            ), f"out.values[{idx}]={val}, but {val} is also in out[{vals_idx[val]}]"
            vals_idx[val] = idx
    for idx in ah.ndindex(out.inverse_indices.shape):
        ridx = int(out.inverse_indices[idx])
        val = out.values[ridx]
        expected = x[idx]
        msg = (
            f"out.inverse_indices[{idx}]={ridx} results in out.values[{ridx}]={val}, "
            f"but should result in x[{idx}]={expected}"
        )
        if dh.is_float_dtype(out.values.dtype) and xp.isnan(expected):
            assert xp.isnan(val), msg
        else:
            assert val == expected, msg
    if dh.is_float_dtype(out.values.dtype):
        assume(x.size <= 128)  # may not be representable
        expected = xp.sum(xp.astype(xp.isnan(x), xp.uint8))
        assert nans == expected, f"{nans} NaNs in out.values, but should be {expected}"


@given(xps.arrays(dtype=xps.scalar_dtypes(), shape=hh.shapes(min_side=1)))
def test_unique_values(x):
    out = xp.unique_values(x)
    ph.assert_dtype("unique_values", x.dtype, out.dtype)
    scalar_type = dh.get_scalar_type(x.dtype)
    distinct = set(scalar_type(x[idx]) for idx in ah.ndindex(x.shape))
    vals_idx = {}
    nans = 0
    for idx in ah.ndindex(out.shape):
        val = scalar_type(out[idx])
        if math.isnan(val):
            nans += 1
        else:
            assert val in distinct, f"out[{idx}]={val}, but {val} not in input array"
            assert (
                val not in vals_idx.keys()
            ), f"out[{idx}]={val}, but {val} is also in out[{vals_idx[val]}]"
            vals_idx[val] = idx
    if dh.is_float_dtype(out.dtype):
        assume(x.size <= 128)  # may not be representable
        expected = xp.sum(xp.astype(xp.isnan(x), xp.uint8))
        assert nans == expected, f"{nans} NaNs in out, but should be {expected}"
