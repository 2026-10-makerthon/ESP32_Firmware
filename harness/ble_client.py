"""Real BLE central. No scan/connect until explicitly invoked by the CLI."""
import asyncio
from collections import deque
import json
from pathlib import Path
import struct
import time
import wave
from .protocol import (SERVICE, AUDIO, CONTROL, EVENT, CAPABILITIES, Command, Event,
                       Op, Status, Capabilities, Reassembler, PROFILES)
from .codec import pcm


async def scan(timeout=5):
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=timeout, return_adv=True, service_uuids=[SERVICE])
    return [{"address":d.address, "name":d.name, "rssi":a.rssi} for d,a in found.values()]


class Client:
    def __init__(self, address, output="build/ble", pair=False):
        self.address, self.output = address, Path(output)
        self.session, self.next_id = 0, 1
        self.events = {}
        self.pending_audio = deque(maxlen=250)
        self.receiver = Reassembler()
        self.lock = asyncio.Lock()
        self.received = self.callback_drops = self.malformed = 0
        self.log = None
        self.client = None
        self.max_pending_audio = 0
        self.pair = pair

    def _event(self, _, data):
        try:
            event = Event.decode(bytes(data))
        except ValueError:
            self.malformed += 1
            return
        if self.session and event.session_id != self.session:
            return
        queue = self.events.get(event.command_id)
        if queue is not None and not queue.full():
            queue.put_nowait(event)
        if self.log:
            self.log.write(json.dumps({"kind":"event", "host_ns":time.monotonic_ns(), "hex":bytes(data).hex()})+"\n")

    def _audio(self, _, data):
        if len(self.pending_audio) == self.pending_audio.maxlen:
            self.callback_drops += 1
        self.pending_audio.append((time.monotonic_ns(), bytes(data)))
        self.max_pending_audio = max(self.max_pending_audio, len(self.pending_audio))

    def _id(self):
        # Do not silently reuse a command ID within a live session.
        if self.next_id > 65535:
            raise RuntimeError("command IDs exhausted; reconnect for a new session")
        cid = self.next_id
        self.next_id += 1
        return cid

    async def command(self, op, args=(), timeout=3, wait_started=False):
        async with self.lock:
            cid = self._id()
            queue = asyncio.Queue(maxsize=8)
            self.events[cid] = queue
            raw = Command(op, cid, self.session, args).encode()
            try:
                t0 = time.monotonic_ns()
                await self.client.write_gatt_char(CONTROL, raw, response=True)
                async with asyncio.timeout(timeout):
                    while True:
                        result = await queue.get()
                        if result.status == Status.REJECTED:
                            raise RuntimeError(f"{op.name} rejected: {result.detail.name}")
                        if wait_started and result.status == Status.ACCEPTED:
                            continue
                        if op == Op.GET_STATE:
                            self.session = result.session_id
                        if op == Op.START_AUDIO and result.status == Status.STARTED:
                            stream, epoch = struct.unpack("<HI", result.extra)
                            self.receiver.reset(stream)
                            self.epoch = epoch
                        if self.log:
                            self.log.write(json.dumps({"kind":"roundtrip", "op":int(op), "start_ns":t0,
                                                       "end_ns":time.monotonic_ns(), "device_ms":result.device_ms})+"\n")
                        return result
            finally:
                self.events.pop(cid, None)

    async def capture(self, seconds=10, play=None):
        from bleak import BleakClient
        self.output.mkdir(parents=True, exist_ok=True)
        # Files are streamed to disk, so long HIL sessions do not accumulate PCM in RAM.
        with (self.output / "events.jsonl").open("w", encoding="utf-8") as log, \
                wave.open(str(self.output / "received.wav"), "wb") as wav:
            self.log = log
            wav.setparams((1,2,16000,0,"NONE","not compressed"))
            async with BleakClient(self.address, pair=self.pair, timeout=30) as client:
                self.client = client
                raw_caps = bytes(await client.read_gatt_char(CAPABILITIES))
                caps = Capabilities.decode(raw_caps)
                if not caps.profiles & 1:
                    raise RuntimeError("device does not support profile 1")
                await client.start_notify(EVENT, self._event)
                await self.command(Op.GET_STATE)
                if client.mtu_size < caps.min_audio_mtu:
                    raise RuntimeError(f"negotiated MTU {client.mtu_size} < {caps.min_audio_mtu}")
                await client.start_notify(AUDIO, self._audio)
                await self.command(Op.SET_DETECTION,(-4500,-5000,500,100))
                await self.command(Op.START_AUDIO,(1,),wait_started=True)
                await self.command(Op.HEARTBEAT)
                try:
                    if play:
                        await self.command(Op.PLAY_PATTERN,(play,80,1,0,5000))
                    start = last_hb = time.monotonic()
                    last_end = None
                    while time.monotonic() - start < seconds:
                        if not client.is_connected:
                            raise ConnectionError("BLE disconnected; start a new capture for a fresh session")
                        if time.monotonic() - last_hb >= .5:
                            await self.command(Op.HEARTBEAT)
                            last_hb = time.monotonic()
                        while self.pending_audio:
                            host_ns, packet = self.pending_audio.popleft()
                            try:
                                frame = self.receiver.push(packet, host_ns // 1000000)
                            except ValueError as error:
                                self.malformed += 1
                                log.write(json.dumps({"kind":"malformed_audio", "error":str(error)})+"\n")
                                continue
                            if frame:
                                samples = pcm(frame)
                                # WAV is concatenated bursts. The sidecar preserves source positions/gaps.
                                wav.writeframesraw(struct.pack(f"<{len(samples)}h", *samples))
                                log.write(json.dumps({"kind":"audio_frame", "host_ns":host_ns, "seq":frame.seq,
                                                     "sample_index":frame.sample_index, "flags":frame.flags,
                                                     "previous_end_sample":last_end})+"\n")
                                last_end = (frame.sample_index+len(samples)) & 0xffffffff
                                self.received += 1
                        await asyncio.sleep(.005)
                finally:
                    if client.is_connected:
                        try:
                            await self.command(Op.STOP_HAPTIC)
                        finally:
                            await self.command(Op.STOP_AUDIO)
                            await client.stop_notify(AUDIO)
                            await client.stop_notify(EVENT)
                summary = {"mode":"real BLE PC client", "address":self.address, "session":self.session,
                           "mtu":client.mtu_size, "frames":self.received, "lost_frames":self.receiver.lost,
                           "malformed":self.malformed, "callback_drops":self.callback_drops,
                           "max_pending_notifications":self.max_pending_audio,
                           "capabilities_hex":raw_caps.hex(), "wav_layout":"concatenated bursts; see events.jsonl",
                           "phy":"unknown", "connection_interval":"unknown", "capture_latency_p95_ms":None,
                           "android_verified":False}
        self.log = None
        (self.output / "summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
        return summary
