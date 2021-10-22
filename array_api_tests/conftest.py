from functools import lru_cache

from pytest import mark

from . import _array_module as xp
from ._array_module import _UndefinedStub


def pytest_addoption(parser):
    parser.addoption(
        '--disable-extension',
        metavar='ext',
        nargs='+',
        default=[],
        help='disable testing for Array API extension(s)',
    )
    parser.addoption(
        '--enable-extension',
        metavar='ext',
        nargs='+',
        default=[],
        help='enable testing for Array API extension(s)',
    )


def pytest_configure(config):
    config.addinivalue_line(
        'markers', 'xp_extension(ext): tests an Array API extension'
    )


@lru_cache
def xp_has_ext(ext: str) -> bool:
    try:
        return not isinstance(getattr(xp, ext), _UndefinedStub)
    except AttributeError:
        return False


def pytest_collection_modifyitems(config, items):
    disabled_exts = config.getoption('--disable-extension')
    enabled_exts = config.getoption('--enable-extension')
    for ext in disabled_exts:
        if ext in enabled_exts:
            raise ValueError(f'{ext=} both enabled and disabled')
    for item in items:
        try:
            ext_mark = next(
                mark for mark in item.iter_markers() if mark.name == 'xp_extension'
            )
        except StopIteration:
            continue
        ext = ext_mark.args[0]
        if ext in disabled_exts:
            item.add_marker(mark.skip(reason=f'{ext} disabled in --disable-extensions'))
        elif not ext in enabled_exts and not xp_has_ext(ext):
            item.add_marker(mark.skip(reason=f'{ext} not found in array module'))
