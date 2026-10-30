import ctypes as C
import json
import random
from pathlib import Path
import pytest
from harness.native import Native
from harness.patterns import duration, strength_at
from harness.protocol import Command, Op, Event, Reassembler, Status, Detail
from harness.device import Device
from harness.protocol import decode_command, ProtocolError

VECTORS=json.loads((Path(__file__).resolve().parents[1]/"contracts/golden_vectors.json").read_text())


@pytest.fixture(scope="module")
def native(native_backend):
    return native_backend


def test_c_parser_and_codec(native):
    for v in VECTORS["commands"]:
        assert native.parse_result(bytes.fromhex(v["hex"]))==v["result"],v["name"]
    for v in VECTORS["adpcm"]:
        block=bytes.fromhex(v["block_hex"])
        assert native.encode(v["input_pcm"])==block,v["name"]
        assert native.decode(block,len(v["input_pcm"]))==v["decoded_pcm"],v["name"]


def test_c_patterns_cross_language(native):
    for pattern in range(1,6):
        for repeat in (1,2,10):
            assert native.lib.sh_pattern_duration(pattern,repeat)==duration(pattern,repeat)
            for ms in range(0,duration(pattern,repeat)+10,5):
                assert native.lib.sh_pattern_level(pattern,73,repeat,ms)==strength_at(pattern,73,repeat,ms)


class Haptic(C.Structure):
    _fields_=[("started",C.c_uint32),("heartbeat",C.c_uint32),("ttl",C.c_uint16),
              ("pattern",C.c_uint8),("strength",C.c_uint8),("repeat",C.c_uint8),
              ("active",C.c_uint8),("level",C.c_uint8),("reason",C.c_uint8)]


def test_c_haptic_lifecycle_wrap(native):
    lib=native.lib
    lib.sh_haptic_init.argtypes=[C.POINTER(Haptic)]
    lib.sh_haptic_start.argtypes=[C.POINTER(Haptic),C.c_uint8,C.c_uint8,C.c_uint8,C.c_uint16,C.c_uint32,C.c_int]
    lib.sh_haptic_tick.argtypes=[C.POINTER(Haptic),C.c_uint32]
    lib.sh_haptic_heartbeat.argtypes=[C.POINTER(Haptic),C.c_uint32]
    lib.sh_haptic_stop.argtypes=[C.POINTER(Haptic)]
    s=Haptic();lib.sh_haptic_init(C.byref(s))
    assert lib.sh_haptic_start(C.byref(s),1,80,1,1000,0,0)==6
    lib.sh_haptic_heartbeat(C.byref(s),0xffffff00)
    assert lib.sh_haptic_start(C.byref(s),5,80,1,5000,0xffffff00,1)==0
    lib.sh_haptic_tick(C.byref(s),(0xffffff00+1500)&0xffffffff)
    assert not s.active and s.level==0 and s.reason==12
    lib.sh_haptic_heartbeat(C.byref(s),1500)
    assert not s.active


class CDevice:
    def __init__(self,lib):
        self.lib=lib
        lib.sh_device_size.restype=C.c_size_t
        self.memory=C.create_string_buffer(lib.sh_device_size())
        lib.sh_device_init.argtypes=[C.c_void_p,C.c_uint32,C.c_int,C.c_int]
        lib.sh_device_transport.argtypes=[C.c_void_p,C.c_uint16,C.c_int,C.c_int]
        lib.sh_device_command.argtypes=[C.c_void_p,C.c_char_p,C.c_size_t,C.c_uint32]
        lib.sh_device_capture.argtypes=[C.c_void_p,C.POINTER(C.c_int16),C.c_void_p,C.c_size_t,C.c_uint32]
        lib.sh_device_event_peek.argtypes=[C.c_void_p,C.c_void_p]
        lib.sh_device_event_pop.argtypes=[C.c_void_p]
        lib.sh_device_audio_packet.argtypes=[C.c_void_p,C.c_uint16,C.c_void_p]
        lib.sh_device_audio_pop.argtypes=[C.c_void_p]
        lib.sh_device_tick.argtypes=[C.c_void_p,C.c_uint32]
        lib.sh_device_init(self.memory,1,0,1)
        lib.sh_device_transport(self.memory,247,1,1)

    def command(self,cmd,now=0):
        raw=cmd.encode()
        return self.lib.sh_device_command(self.memory,raw,len(raw),now)

    def events(self):
        events=[];out=C.create_string_buffer(20)
        while n:=self.lib.sh_device_event_peek(self.memory,out):
            events.append(Event.decode(out.raw[:n]))
            self.lib.sh_device_event_pop(self.memory)
        return events

    def audio(self):
        frames=[];out=C.create_string_buffer(244);receiver=Reassembler()
        while n:=self.lib.sh_device_audio_packet(self.memory,0,out):
            frames.append(receiver.push(out.raw[:n],0))
            self.lib.sh_device_audio_pop(self.memory)
        return frames


def test_c_device_matches_reference_commands_and_audio(native):
    c=CDevice(native.lib)
    py=Device(simulation=True)
    py.event_subscribed=py.audio_subscribed=True
    cmds=[Command(Op.GET_STATE,1,0),Command(Op.SET_DETECTION,2,1,(-4500,-5000,0,100)),
          Command(Op.START_AUDIO,3,1,(1,)),Command(Op.HEARTBEAT,4,1),
          Command(Op.PLAY_PATTERN,5,1,(2,80,1,0,1000))]
    for cmd in cmds:
        assert c.command(cmd)==0
        py.command(cmd.encode())
    assert c.events()==list(py.events)
    py.events.clear()
    for frame_no in range(40):
        now=frame_no*20
        c.lib.sh_device_tick(c.memory,now);py.tick(now)
        samples=[6000 if i%2 else -6000 for i in range(320)] if frame_no in (10,11,15,16) else [0]*320
        buf=(C.c_int16*320)(*samples)
        assert c.lib.sh_device_capture(c.memory,buf,None,320,now)==0
        py.capture(samples,now)
        assert c.events()==list(py.events)
        py.events.clear()
        expected=[]
        while py.audio.queue:expected.append(py.audio.pop())
        assert c.audio()==expected


def test_c_device_cache_stop_session_and_mtu(native):
    c=CDevice(native.lib)
    cmd=Command(Op.PLAY_PATTERN,1,1,(3,80,1,0,1000))
    assert c.command(cmd)==0
    c.events()
    assert c.command(cmd,100)==0
    assert c.events()[0].status==Status.STARTED
    assert c.command(Command(Op.PLAY_PATTERN,1,1,(1,80,1,0,1000)))==Detail.COMMAND_ID_CONFLICT
    assert c.command(Command(Op.STOP_HAPTIC,2,2))==Detail.SESSION_MISMATCH
    for cid in range(2,65):c.command(Command(Op.GET_STATE,cid,1))
    assert c.command(Command(Op.STOP_HAPTIC,200,1))==0
    assert c.events()[-1].status==Status.STOPPED
    c.lib.sh_device_init(c.memory,2,0,0)
    c.lib.sh_device_transport(c.memory,23,1,1)
    assert c.command(Command(Op.START_AUDIO,1,2,(1,)))==Detail.MTU_TOO_SMALL


def test_c_and_python_reject_same_fuzzed_commands(native):
    rng=random.Random(49013)
    for i in range(2000):
        if i%2:
            raw=bytearray(rng.randbytes(rng.randrange(0,25)))
        else:
            raw=bytearray(Command(Op.PLAY_PATTERN,1,1,(2,80,1,0,1000)).encode())
            raw[rng.randrange(len(raw))]=rng.randrange(256)
        try:
            decode_command(bytes(raw));expected=0
        except ProtocolError as error:
            expected=int(error.detail)
        assert native.parse_result(bytes(raw))==expected


def test_c_30_minute_heartbeat_does_not_exhaust_cache(native):
    c=CDevice(native.lib)
    for step in range(3600):
        now=step*500
        assert c.command(Command(Op.HEARTBEAT,step+1,1),now)==0
        if step%20==0:
            assert c.command(Command(Op.PLAY_PATTERN,10000+step,1,(1,80,1,0,1000)),now)==0
        c.lib.sh_device_tick(c.memory,now+250)
        c.events()


def test_c_30_minute_audio_and_haptics_with_repeated_300ms_congestion(native):
    c=CDevice(native.lib)
    assert c.command(Command(Op.START_AUDIO,60000,1,(1,)))==0
    samples=(C.c_int16*320)(*[6000 if i%2 else -6000 for i in range(320)])
    packet=C.create_string_buffer(244)
    delivered=discontinuities=0
    hb_id=1
    for frame in range(90000): #30min at50frames/s, fake time; not a radio performance test
        now=frame*20
        if frame%25==0:
            assert c.command(Command(Op.HEARTBEAT,hb_id,1),now)==0
            hb_id+=1
        if frame%250==0:
            assert c.command(Command(Op.PLAY_PATTERN,10000+frame//250,1,(1,80,1,0,1000)),now)==0
        c.lib.sh_device_tick(c.memory,now)
        assert c.lib.sh_device_capture(c.memory,samples,None,320,now)==0
        if frame%500>=15:
            batch=0
            while n:=c.lib.sh_device_audio_packet(c.memory,0,packet):
                assert n==180
                delivered+=1;batch+=1
                discontinuities+=bool(packet.raw[2]&2)
                c.lib.sh_device_audio_pop(c.memory)
            assert batch<=5
        if frame%25==0:c.events()
    assert delivered==88020 and discontinuities==180
    c.lib.sh_device_disconnect.argtypes=[C.c_void_p]
    c.lib.sh_device_state.argtypes=[C.c_void_p]
    c.lib.sh_device_state.restype=C.c_uint8
    c.lib.sh_device_disconnect(c.memory)
    assert c.lib.sh_device_state(c.memory)==0
