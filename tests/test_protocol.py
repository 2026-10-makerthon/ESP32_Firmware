import json
from pathlib import Path
import struct
import pytest
from harness.protocol import *

VECTORS = json.loads((Path(__file__).resolve().parents[1]/"contracts/golden_vectors.json").read_text())


@pytest.mark.parametrize("vector",VECTORS["commands"],ids=lambda v:v["name"])
def test_commands(vector):
    raw=bytes.fromhex(vector["hex"])
    if vector["result"]:
        with pytest.raises(ProtocolError) as exc:
            decode_command(raw)
        assert exc.value.detail==vector["result"]
    else:
        assert decode_command(raw).encode()==raw


def test_capabilities_and_event():
    caps=Capabilities()
    assert len(caps.encode())==20
    assert Capabilities.decode(caps.encode())==caps
    assert caps.encode().hex()=="01001e071f640a008813f401dc05b900f4000000"
    event=Event(2,3,0x12345678,Status.STARTED,device_ms=100,extra=struct.pack("<HI",1,80))
    assert len(event.encode())==20
    assert Event.decode(event.encode())==event
    with pytest.raises(ProtocolError): Event.decode(event.encode()+b"x")


@pytest.mark.parametrize("profile",[1,2,3])
@pytest.mark.parametrize("mtu",[23,185,247,517])
def test_fragmentation(profile,mtu):
    body=bytes(i%256 for i in range(PROFILES[profile][2]))
    frame=AudioFrame(profile,1,5,320,body,int(Flags.BURST_START))
    packets=frame.packets(mtu)
    receiver=Reassembler()
    # Out-of-order fragments of the same frame are permitted.
    actual=None
    for p in reversed(packets):
        result=receiver.push(p,0)
        if result: actual=result
    assert actual==frame


def test_overlap_duplicate_timeout_and_limits():
    f=AudioFrame(1,1,0,0,bytes(164))
    packets=f.packets(23)
    r=Reassembler(limit=2)
    assert r.push(packets[0],0) is None
    assert r.push(packets[0],1) is None
    bad=bytearray(packets[1]);bad[14:16]=struct.pack("<H",1)
    with pytest.raises(ProtocolError):r.push(bad,2)
    r.push(packets[0],3)
    r.push(packets[1],103)
    assert r.expired==1
    for seq in range(1,5):r.push(AudioFrame(1,1,seq,seq*320,bytes(164)).packets(23)[0],104)
    assert len(r.pending)==2


def test_wrap_and_silence_not_loss():
    r=Reassembler()
    assert r.push(AudioFrame(1,2,65535,0xfffffec0,bytes(164)).packets()[0],0)
    assert r.push(AudioFrame(1,2,0,0,bytes(164),4).packets()[0],1)
    assert r.lost==0
    assert r.push(AudioFrame(1,2,1,32000,bytes(164),4).packets()[0],2)
    assert r.lost==0
    assert r.push(AudioFrame(1,2,3,32640,bytes(164)).packets()[0],3)
    assert r.lost==1
    assert r.push(AudioFrame(1,2,2,32320,bytes(164)).packets()[0],4) is None
    with pytest.raises(ProtocolError):r.push(AudioFrame(1,3,0,0,bytes(164)).packets()[0],5)


@pytest.mark.parametrize("raw",[b"",bytes(16),b"\x01"*245])
def test_malformed_audio(raw):
    with pytest.raises(ProtocolError):Reassembler().push(raw,0)


def test_expired_frame_cannot_be_revived_by_late_fragments():
    packets=AudioFrame(1,1,4,1280,bytes(164)).packets(23)
    receiver=Reassembler()
    receiver.push(packets[0],0)
    for packet in packets:
        assert receiver.push(packet,101) is None
    assert receiver.expired==1 and not receiver.pending


def test_bad_fragment_metadata_and_invalid_index():
    packets=AudioFrame(1,1,4,1280,bytes(164)).packets(23)
    r=Reassembler();r.push(packets[0],0)
    altered=bytearray(packets[1]);altered[2]=1
    with pytest.raises(ProtocolError):r.push(altered,1)
