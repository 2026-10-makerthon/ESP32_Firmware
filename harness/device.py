"""Executable device reference. Clock is injected; this does not emulate radio."""
from collections import OrderedDict, deque
import struct
from .protocol import (Command, Event, Detail, Op, Status, StateFlags, ProtocolError,
                       Capabilities, decode_command)
from .patterns import duration, strength_at
from .audio import AudioPipeline


def elapsed(now, then):
    return (now - then) & 0xffffffff


class MockHapticDriver:
    def __init__(self):
        self.level = 0
        self.changes = []

    def set(self, now, level):
        if level != self.level:
            self.changes.append((now, level))
            self.level = level


class Device:
    def __init__(self, *, haptic_verified=False, simulation=False, prototype_output=False, session=1):
        self.haptic_verified, self.simulation = haptic_verified, simulation
        self.prototype_output = bool(prototype_output)
        self.driver = MockHapticDriver()
        self.session = session or 1
        self.stream = 0
        self.mtu = 247
        self.audio_subscribed = self.event_subscribed = False
        self.detection = (-4500,-5000,500,100)
        self.audio = self.playing = None
        self.start_command = None
        self.capture_epoch = None
        self.last_heartbeat = 0
        self.cache = OrderedDict()
        self.events = deque(maxlen=128)

    def connect(self, session, now=0):
        if not session or session == self.session:
            raise ValueError("a new nonzero session is required")
        self.disconnect(now)
        self.session = session

    def disconnect(self, now=0):
        self.driver.set(now, 0)
        self.playing = self.audio = self.start_command = self.capture_epoch = None
        self.audio_subscribed = self.event_subscribed = False
        self.cache.clear()
        self.events.clear()

    def capabilities(self):
        return Capabilities(features=0x0e | int(self.haptic_verified) | (0x10 if self.simulation else 0)).encode()

    def transport(self, mtu, audio_subscribed, event_subscribed, now=0):
        self.mtu = mtu
        self.audio_subscribed = bool(audio_subscribed)
        self.event_subscribed = bool(event_subscribed)
        if not self.event_subscribed:
            self.driver.set(now,0)
            self.playing = None
        if not self.audio_subscribed or not self.event_subscribed:
            self.audio = self.start_command = self.capture_epoch = None

    @property
    def state(self):
        return int((StateFlags.ARMED if self.audio else 0) |
                   (StateFlags.TRANSMITTING if self.audio and self.audio.transmitting else 0) |
                   (StateFlags.HAPTIC_RUNNING if self.playing else 0) |
                   (StateFlags.HARDWARE_VERIFIED if self.haptic_verified else 0) |
                   (StateFlags.AUDIO_SUBSCRIBED if self.audio_subscribed else 0) |
                   (StateFlags.EVENT_SUBSCRIBED if self.event_subscribed else 0))

    def _enqueue(self, event, now):
        if len(self.events) == self.events.maxlen:
            # Event backpressure fails closed; never lose safety by waiting on BLE.
            self.driver.set(now, 0)
            self.playing = None
        self.events.append(event)

    def _event(self, cmd, status, now, detail=Detail.OK, extra=b"", cache=True):
        event = Event(int(cmd.op), cmd.command_id, self.session, status, detail, now, extra)
        self._enqueue(event,now)
        if cache and cmd.command_id in self.cache:
            raw, _, stamp = self.cache[cmd.command_id]
            self.cache[cmd.command_id] = (raw, event, stamp)
        return event

    def command(self, raw, now=0):
        try:
            cmd = decode_command(raw)
        except ProtocolError as error:
            if len(raw) < 8:
                raise  # transport must reject uncorrelatable packets
            _, op, cid, _ = struct.unpack_from("<BBHI", raw)
            return self._event(Command(op, cid, self.session), Status.REJECTED, now, error.detail, cache=False)
        if cmd.session_id != self.session and not (cmd.op == Op.GET_STATE and cmd.session_id == 0):
            return self._event(cmd, Status.REJECTED, now, Detail.SESSION_MISMATCH, cache=False)
        # Heartbeats have no execution side effects and use a dedicated lease path.
        # They must not fill the 64-entry execution replay cache in 32 seconds.
        if cmd.op == Op.HEARTBEAT:
            if cmd.command_id in self.cache:
                return self._event(cmd, Status.REJECTED, now, Detail.COMMAND_ID_CONFLICT, cache=False)
            self.tick(now)
            self.last_heartbeat = now
            return self._event(cmd, Status.COMPLETED, now, cache=False)
        for key, (_, event, stamp) in list(self.cache.items()):
            active = (self.playing and self.playing[0].command_id == key) or (
                self.start_command and self.start_command.command_id == key)
            if elapsed(now, stamp) >= 60000 and not active:
                del self.cache[key]
        if cmd.command_id in self.cache:
            previous, event, _ = self.cache[cmd.command_id]
            if previous != raw:
                return self._event(cmd, Status.REJECTED, now, Detail.COMMAND_ID_CONFLICT, cache=False)
            self._enqueue(event,now)
            return event
        # STOP and HEARTBEAT retain a reserved processing path even when cache is full.
        bypass_cache = len(self.cache) >= 64 and cmd.op in (Op.STOP_HAPTIC, Op.HEARTBEAT, Op.STOP_AUDIO)
        if len(self.cache) >= 64 and not bypass_cache:
            return self._event(cmd, Status.REJECTED, now, Detail.CACHE_FULL, cache=False)
        if not bypass_cache:
            self.cache[cmd.command_id] = (bytes(raw), None, now)
        emit = lambda status, detail=Detail.OK, extra=b"": self._event(cmd, status, now, detail, extra, not bypass_cache)
        if cmd.op == Op.GET_STATE:
            return emit(Status.COMPLETED, extra=struct.pack("<HBB", self.stream, self.state, self.audio.profile if self.audio else 0))
        if cmd.op == Op.STOP_HAPTIC:
            self._stop(now)
            return emit(Status.STOPPED)
        if cmd.op == Op.STOP_AUDIO:
            if self.start_command:
                self._event(self.start_command, Status.STOPPED, now)
            self.audio = self.start_command = self.capture_epoch = None
            return emit(Status.STOPPED)
        if not self.event_subscribed:
            return emit(Status.REJECTED, Detail.NOT_SUBSCRIBED)
        if cmd.op == Op.SET_DETECTION:
            if self.audio:
                return emit(Status.REJECTED, Detail.BUSY)
            self.detection = cmd.args
            return emit(Status.COMPLETED)
        if cmd.op == Op.START_AUDIO:
            if self.audio:
                return emit(Status.REJECTED, Detail.BUSY)
            if not self.audio_subscribed:
                return emit(Status.REJECTED, Detail.NOT_SUBSCRIBED)
            if self.mtu < 185:
                return emit(Status.REJECTED, Detail.MTU_TOO_SMALL)
            self.stream = (self.stream + 1) & 65535
            self.audio = AudioPipeline(cmd.args[0], self.stream, self.detection)
            self.start_command = cmd
            self.capture_epoch = None
            return emit(Status.ACCEPTED)
        if cmd.op == Op.PLAY_PATTERN:
            self.tick(now)
            pattern, strength, repeat, _, ttl = cmd.args
            if not (self.haptic_verified or self.simulation or self.prototype_output):
                return emit(Status.REJECTED, Detail.HARDWARE_UNVERIFIED)
            if self.playing:
                return emit(Status.REJECTED, Detail.BUSY)
            if duration(pattern, repeat) > ttl:
                return emit(Status.REJECTED, Detail.BAD_VALUE)
            if elapsed(now, self.last_heartbeat) >= 1500:
                return emit(Status.REJECTED, Detail.LEASE_EXPIRED)
            self.playing = (cmd, now)
            self.driver.set(now, strength_at(pattern, strength, repeat, 0))
            return emit(Status.STARTED)
        return emit(Status.REJECTED, Detail.UNKNOWN_OPCODE)

    def _stop(self, now, detail=Detail.OK, completed=False):
        if self.playing:
            cmd, _ = self.playing
            self.playing = None
            self.driver.set(now, 0)
            self._event(cmd, Status.COMPLETED if completed else Status.STOPPED, now, detail)

    def tick(self, now):
        if not self.playing:
            return
        cmd, start = self.playing
        pattern, strength, repeat, _, ttl = cmd.args
        age = elapsed(now, start)
        if elapsed(now, self.last_heartbeat) >= 1500:
            self._stop(now, Detail.LEASE_EXPIRED)
        elif age >= duration(pattern, repeat):
            self._stop(now, completed=True)
        elif age >= ttl:
            self._stop(now, Detail.TTL_EXPIRED)
        else:
            self.driver.set(now, strength_at(pattern, strength, repeat, age))

    def capture(self, samples, first_sample_ms, detection_samples=None):
        if not self.audio:
            return
        if self.capture_epoch is None:
            self.capture_epoch = first_sample_ms & 0xffffffff
            self._event(self.start_command, Status.STARTED, first_sample_ms,
                        extra=struct.pack("<HI", self.stream, self.capture_epoch))
        self.audio.feed(samples, self.driver.level != 0, detection_samples)
