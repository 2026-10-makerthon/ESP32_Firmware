import ctypes as C
import pytest
from harness.native import Native


class Button(C.Structure):
    _fields_ = [("changed_at", C.c_uint32), ("pressed_at", C.c_uint32),
                ("raw", C.c_uint8), ("stable", C.c_uint8),
                ("running", C.c_uint8), ("consumed", C.c_uint8)]


@pytest.fixture(scope="module")
def lib(native_backend):
    lib = native_backend.lib
    lib.sh_button_init.argtypes = [C.POINTER(Button), C.c_int, C.c_int, C.c_uint32]
    lib.sh_button_update.argtypes = [C.POINTER(Button), C.c_int, C.c_uint32]
    return lib


def create(lib, running=False, pressed=True, now=0):
    b = Button()
    lib.sh_button_init(C.byref(b), running, pressed, now)
    return b


def tick(lib, b, pressed, now):
    return lib.sh_button_update(C.byref(b), pressed, now & 0xffffffff)


@pytest.mark.parametrize("duration,expected", [(20, 1), (2999, 1), (3000, 2), (5999, 2), (6000, 3)])
def test_release_boundaries(lib, duration, expected):
    b = create(lib)
    assert tick(lib, b, False, duration) == 0
    assert tick(lib, b, False, duration + 30) == expected


def test_pair_hold_is_not_reinterpreted_as_power_off(lib):
    b = create(lib)
    assert tick(lib, b, True, 3000) == 0
    assert tick(lib, b, True, 5999) == 0
    assert tick(lib, b, True, 6000) == 3
    assert tick(lib, b, True, 12000) == 0
    assert tick(lib, b, False, 12001) == 0
    assert tick(lib, b, False, 12031) == 0
    assert tick(lib, b, True, 13000) == 0
    assert tick(lib, b, True, 13030) == 0
    assert tick(lib, b, True, 15999) == 0
    assert tick(lib, b, True, 16000) == 1


def test_boot_gesture_consumed_and_bounce_ignored(lib):
    b = create(lib, running=True)
    assert tick(lib, b, True, 9000) == 0
    tick(lib, b, False, 9001)
    tick(lib, b, True, 9010)  # release bounce
    assert tick(lib, b, True, 11000) == 0
    tick(lib, b, False, 11001)
    tick(lib, b, False, 11031)
    tick(lib, b, True, 12000)
    tick(lib, b, False, 12010)  # press bounce < 30 ms
    assert tick(lib, b, False, 16000) == 0


def test_clock_wrap_and_release_debounce_do_not_extend_hold(lib):
    start = 0xffffff00
    b = create(lib, now=start)
    assert tick(lib, b, True, start + 5999) == 0
    assert tick(lib, b, True, start + 6000) == 3
    b = create(lib, running=True, pressed=False, now=start)
    tick(lib, b, True, start + 10)
    tick(lib, b, True, start + 40)
    tick(lib, b, False, start + 3009)
    assert tick(lib, b, False, start + 3039) == 0
