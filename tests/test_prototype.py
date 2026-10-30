import ctypes as C
from harness.device import Device
from harness.protocol import Command,Op,Status,Detail
from test_native import CDevice


def test_explicit_prototype_accepts_patterns_without_verified_capability(native_backend):
    lib=native_backend.lib
    lib.sh_device_allow_prototype.argtypes=[C.c_void_p,C.c_int]
    lib.sh_device_capabilities.argtypes=[C.c_void_p,C.c_void_p]
    lib.sh_device_state.argtypes=[C.c_void_p]
    lib.sh_device_disconnect.argtypes=[C.c_void_p]
    c=CDevice(lib)
    lib.sh_device_init(c.memory,1,0,0)
    lib.sh_device_transport(c.memory,247,1,1)
    assert c.command(Command(Op.PLAY_PATTERN,1,1,(5,80,1,0,5000)))==Detail.HARDWARE_UNVERIFIED
    c.events()
    lib.sh_device_allow_prototype(c.memory,1)
    py=Device(prototype_output=True)
    py.transport(247,True,True)
    for cmd in (Command(Op.HEARTBEAT,2,1),Command(Op.PLAY_PATTERN,3,1,(5,80,1,0,5000))):
        assert c.command(cmd)==0
        py.command(cmd.encode())
    assert c.events()==list(py.events)
    caps=C.create_string_buffer(20)
    lib.sh_device_capabilities(c.memory,caps)
    assert caps.raw==py.capabilities() and caps.raw[2]==0x0e
    assert not lib.sh_device_state(c.memory)&8
    assert lib.sh_device_state(c.memory)&4
    lib.sh_device_tick(c.memory,1500);py.tick(1500)
    assert not lib.sh_device_state(c.memory)&4 and py.driver.level==0
    # Lease expiry remains enforced; a fresh heartbeat can only start a new command.
    assert c.command(Command(Op.PLAY_PATTERN,4,1,(1,80,1,0,1000)),1501)==Detail.LEASE_EXPIRED
    lib.sh_device_disconnect(c.memory)
    lib.sh_device_transport(c.memory,247,1,1)
    assert c.command(Command(Op.HEARTBEAT,5,1),1600)==0
    assert c.command(Command(Op.PLAY_PATTERN,6,1,(1,80,1,0,1000)),1600)==0
    # Revoking local prototype permission stops output and prevents future PLAY.
    lib.sh_device_allow_prototype(c.memory,0)
    assert not lib.sh_device_state(c.memory)&4
    assert c.command(Command(Op.PLAY_PATTERN,7,1,(1,80,1,0,1000)),1601)==Detail.HARDWARE_UNVERIFIED
