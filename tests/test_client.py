import asyncio
from types import SimpleNamespace
from harness.ble_client import Client
from harness.protocol import Command, Event, Op, Status


def test_client_serializes_gatt_and_decodes_events(tmp_path):
    async def check():
        c=Client("FAKE",tmp_path)
        active=0
        class Fake:
            async def write_gatt_char(self,uuid,raw,response):
                nonlocal active
                active+=1
                assert active==1 and response
                await asyncio.sleep(0)
                from harness.protocol import decode_command
                cmd=decode_command(raw)
                event=Event(int(cmd.op),cmd.command_id,17,Status.COMPLETED,extra=b"\0"*4 if cmd.op==Op.GET_STATE else b"")
                c._event(None,event.encode())
                active-=1
        c.client=Fake()
        await c.command(Op.GET_STATE)
        assert c.session==17
        await asyncio.gather(c.command(Op.HEARTBEAT),c.command(Op.STOP_HAPTIC))
        assert not c.events
    asyncio.run(check())


def test_audio_callback_bounded(tmp_path):
    c=Client("FAKE",tmp_path)
    for _ in range(300):c._audio(None,b"abc")
    assert len(c.pending_audio)==250 and c.callback_drops==50


def test_pair_then_automatic_arm_and_stop_with_existing_wire_contract(tmp_path,monkeypatch):
    import sys
    import struct
    from harness.protocol import CAPABILITIES, EVENT, Capabilities, decode_command
    calls=[]
    class FakeBleak:
        mtu_size=185
        is_connected=True
        def __init__(self,address,*,pair,timeout):
            assert address=="FAKE" and pair and timeout>=10
            calls.append("bonded")
        async def __aenter__(self):return self
        async def __aexit__(self,*_):pass
        async def read_gatt_char(self,uuid):
            assert uuid==CAPABILITIES
            return Capabilities().encode()
        async def start_notify(self,uuid,callback):
            if uuid==EVENT:self.callback=callback
        async def stop_notify(self,uuid):pass
        async def write_gatt_char(self,uuid,raw,response):
            cmd=decode_command(raw);calls.append(cmd.op)
            status=Status.COMPLETED;extra=b""
            if cmd.op==Op.GET_STATE:extra=b"\0"*4
            elif cmd.op==Op.START_AUDIO:
                assert cmd.args==(1,)
                status=Status.STARTED;extra=struct.pack("<HI",1,123)
            elif cmd.op in (Op.STOP_AUDIO,Op.STOP_HAPTIC):status=Status.STOPPED
            self.callback(None,Event(int(cmd.op),cmd.command_id,17,status,extra=extra).encode())
    monkeypatch.setitem(sys.modules,"bleak",SimpleNamespace(BleakClient=FakeBleak))
    result=asyncio.run(Client("FAKE",tmp_path,pair=True).capture(seconds=0))
    assert calls==["bonded",Op.GET_STATE,Op.SET_DETECTION,Op.START_AUDIO,Op.HEARTBEAT,Op.STOP_HAPTIC,Op.STOP_AUDIO]
    assert result["frames"]==0 and result["session"]==17
