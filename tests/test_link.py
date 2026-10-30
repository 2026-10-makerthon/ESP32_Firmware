import ctypes as C
import itertools


def test_pairing_window_deadline_and_wrap(native_backend):
    lib=native_backend.lib
    lib.sh_link_pairing_open.argtypes=[C.c_int,C.c_uint32,C.c_uint32,C.c_uint32]
    start=0xffffff00
    for open in (0,1):
        for elapsed in (0,119999,120000,120001):
            assert lib.sh_link_pairing_open(open,start,(start+elapsed)&0xffffffff,120000)==(open and elapsed<120000)


def test_only_saved_peer_outside_pairing_and_nobody_during_shutdown(native_backend):
    lib=native_backend.lib
    lib.sh_link_admit.argtypes=[C.c_int]*3
    for stopping,pairing,known in itertools.product((0,1),repeat=3):
        assert lib.sh_link_admit(stopping,pairing,known)==(not stopping and (pairing or known))


def test_audio_and_commands_require_completed_bond_encryption_and_live_window(native_backend):
    lib=native_backend.lib
    lib.sh_link_authorize.argtypes=[C.c_int]*8
    for stopping,status,fresh,pairing,encrypted,bonded,known in itertools.product((0,1),repeat=7):
        for key_size in (7,15,16):
            expected=(not stopping and not status and (not fresh or pairing) and encrypted
                      and bonded and key_size==16 and known)
            assert lib.sh_link_authorize(stopping,status,fresh,pairing,encrypted,bonded,key_size,known)==expected
