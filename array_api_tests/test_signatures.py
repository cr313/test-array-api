import inspect

import pytest

from ._array_module import mod, mod_name

from .function_stubs import elementwise

def raises(exceptions, function, message=''):
    try:
        function()
    except exceptions:
        return
    except Exception as e:
        if message:
            raise AssertionError(f"Unexpected exception {e!r} (expected {exceptions}): {message}")
        raise AssertionError(f"Unexpected exception {e!r} (expected {exceptions})")
    raise AssertionError(message)

def doesnt_raise(function, message=''):
    if not callable(function):
        raise ValueError("doesnt_raise should take a lambda")
    try:
        function()
    except Exception as e:
        if message:
            raise AssertionError(f"Unexpected exception {e!r}: {message}")
        raise AssertionError(f"Unexpected exception {e!r}")

@pytest.mark.parametrize('name', elementwise._names)
def test_has_names_elementwise(name):
    assert hasattr(mod, name), f"{mod_name} is missing the elementwise function {name}()"

@pytest.mark.parametrize('name', elementwise._names)
def test_function_positional_args(name):
    if not hasattr(mod, name):
        pytest.skip(f"{mod_name} does not have {name}(), skipping.")
    stub_func = getattr(elementwise, name)
    mod_func = getattr(mod, name)
    args = inspect.getfullargspec(stub_func).args
    nargs = len(args)

    a = mod.array([1.])

    for n in range(nargs+2):
        if n == nargs:
            doesnt_raise(lambda: mod_func(*[a]*n))
        else:
            # NumPy ufuncs raise ValueError instead of TypeError
            raises((TypeError, ValueError), lambda: mod_func(*[a]*n), f"{name}() should not accept {n} positional arguments")

@pytest.mark.parametrize('name', elementwise._names)
def test_function_keyword_only_args(name):
    if not hasattr(mod, name):
        pytest.skip(f"{mod_name} does not have {name}(), skipping.")
    stub_func = getattr(elementwise, name)
    mod_func = getattr(mod, name)
    args = inspect.getfullargspec(stub_func).args
    kwonlyargs = inspect.getfullargspec(stub_func).kwonlyargs
    nargs = len(args)

    a = mod.array([1.])
    b = mod.array([1.])
    for arg in kwonlyargs:
        # The "only" part of keyword-only is tested by the positional test above.
        doesnt_raise(lambda: mod_func(*[a]*nargs, **{arg: b}),
                     f"{name}() should accept the keyword-only argument {arg}")
