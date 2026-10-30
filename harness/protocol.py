"""Wire contract v1. See contracts/protocol.md; all integers are little endian."""
from dataclasses import dataclass
from enum import IntEnum, IntFlag
import struct

VERSION = 1
SERVICE = "8e1f0000-6f5a-4d7c-a321-9b7e2c1048d0"
AUDIO, CONTROL, EVENT, CAPABILITIES = [
    f"8e1f000{i}-6f5a-4d7c-a321-9b7e2c1048d0" for i in range(1, 5)
]
PROFILES = {1: (16000, 320, 164), 2: (8000, 160, 84), 3: (16000, 320, 640)}
COMMAND_HEADER = struct.Struct("<BBHI")
AUDIO_HEADER = struct.Struct("<BBBBHHIHH")


class Op(IntEnum):
    GET_STATE = 1
    START_AUDIO = 2
    STOP_AUDIO = 3
    SET_DETECTION = 4
    PLAY_PATTERN = 0x10
    STOP_HAPTIC = 0x11
    HEARTBEAT = 0x20


class Status(IntEnum):
    ACCEPTED = 1
    STARTED = 2
    COMPLETED = 3
    STOPPED = 4
    REJECTED = 5


class Detail(IntEnum):
    OK = 0
    BAD_LENGTH = 1
    BAD_VERSION = 2
    BAD_VALUE = 3
    BUSY = 4
    SESSION_MISMATCH = 5
    HARDWARE_UNVERIFIED = 6
    MTU_TOO_SMALL = 7
    INTERNAL = 8
    UNKNOWN_OPCODE = 9
    COMMAND_ID_CONFLICT = 10
    NOT_SUBSCRIBED = 11
    LEASE_EXPIRED = 12
    TTL_EXPIRED = 13
    CACHE_FULL = 14


class Flags(IntFlag):
    MOTOR_ACTIVE = 1
    DISCONTINUITY = 2
    BURST_START = 4
    BURST_END = 8
    PRE_ROLL = 16


class StateFlags(IntFlag):
    ARMED = 1
    TRANSMITTING = 2
    HAPTIC_RUNNING = 4
    HARDWARE_VERIFIED = 8
    AUDIO_SUBSCRIBED = 16
    EVENT_SUBSCRIBED = 32


class ProtocolError(ValueError):
    def __init__(self, detail, message=""):
        self.detail = Detail(detail)
        super().__init__(message or self.detail.name)


@dataclass(frozen=True)
class Command:
    op: Op
    command_id: int
    session_id: int
    args: tuple = ()

    def encode(self):
        fmt = FORMATS[self.op]
        raw = COMMAND_HEADER.pack(VERSION, self.op, self.command_id, self.session_id)
        raw += struct.pack(fmt, *self.args)
        decode_command(raw)
        return raw


FORMATS = {Op.GET_STATE: "<", Op.START_AUDIO: "<B", Op.STOP_AUDIO: "<",
           Op.SET_DETECTION: "<hhHH", Op.PLAY_PATTERN: "<BBBBH",
           Op.STOP_HAPTIC: "<", Op.HEARTBEAT: "<"}


def decode_command(raw):
    if len(raw) < 8 or len(raw) > 20:
        raise ProtocolError(Detail.BAD_LENGTH)
    version, opcode, cid, session = COMMAND_HEADER.unpack_from(raw)
    if version != VERSION:
        raise ProtocolError(Detail.BAD_VERSION)
    try:
        op = Op(opcode)
    except ValueError:
        raise ProtocolError(Detail.UNKNOWN_OPCODE) from None
    fmt = FORMATS[op]
    if len(raw) != 8 + struct.calcsize(fmt):
        raise ProtocolError(Detail.BAD_LENGTH)
    args = struct.unpack_from(fmt, raw, 8)
    if op == Op.START_AUDIO and args[0] not in PROFILES:
        raise ProtocolError(Detail.BAD_VALUE)
    if op == Op.SET_DETECTION:
        on, off, hold, pre = args
        if not (-9000 <= on <= 0 and -9000 <= off <= on - 300 and
                hold <= 5000 and pre <= 100 and pre % 20 == 0):
            raise ProtocolError(Detail.BAD_VALUE)
    if op == Op.PLAY_PATTERN:
        pattern, strength, repeat, reserved, ttl = args
        if not (1 <= pattern <= 5 and 1 <= strength <= 100 and
                1 <= repeat <= 10 and reserved == 0 and 1 <= ttl <= 5000):
            raise ProtocolError(Detail.BAD_VALUE)
    return Command(op, cid, session, args)


@dataclass(frozen=True)
class Event:
    opcode: int
    command_id: int
    session_id: int
    status: Status
    detail: Detail = Detail.OK
    device_ms: int = 0
    extra: bytes = b""

    def encode(self):
        raw = COMMAND_HEADER.pack(VERSION, self.opcode, self.command_id, self.session_id)
        return raw + struct.pack("<BBI", self.status, self.detail, self.device_ms & 0xffffffff) + self.extra

    @classmethod
    def decode(cls, raw):
        if len(raw) < 14 or len(raw) > 20:
            raise ProtocolError(Detail.BAD_LENGTH)
        ver, op, cid, sid = COMMAND_HEADER.unpack_from(raw)
        if ver != VERSION:
            raise ProtocolError(Detail.BAD_VERSION)
        try:
            status, detail, ms = struct.unpack_from("<BBI", raw, 8)
            status, detail = Status(status), Detail(detail)
        except ValueError:
            raise ProtocolError(Detail.BAD_VALUE) from None
        extra_len = 4 if op == Op.GET_STATE and status != Status.REJECTED else (
            6 if op == Op.START_AUDIO and status == Status.STARTED else 0)
        if len(raw) != 14 + extra_len:
            raise ProtocolError(Detail.BAD_LENGTH)
        return cls(op, cid, sid, status, detail, ms, bytes(raw[14:]))


@dataclass(frozen=True)
class Capabilities:
    """20-byte capability value. profile/pattern bits are indexed by ID-1."""
    features: int = 0x1e  # gate, heartbeat, fragmentation, simulation; no physical haptic
    profiles: int = 7
    patterns: int = 31
    max_strength: int = 100
    max_repeat: int = 10
    ttl_ms: int = 5000
    heartbeat_ms: int = 500
    lease_ms: int = 1500
    min_audio_mtu: int = 185
    max_notify: int = 244

    def encode(self):
        return struct.pack("<BBBBBBHHHHHHH", 1, 0, self.features, self.profiles,
                           self.patterns, self.max_strength, self.max_repeat,
                           self.ttl_ms, self.heartbeat_ms, self.lease_ms,
                           self.min_audio_mtu, self.max_notify, 0)

    @classmethod
    def decode(cls, raw):
        if len(raw) != 20:
            raise ProtocolError(Detail.BAD_LENGTH)
        major, minor, features, profiles, patterns, strength, repeat, ttl, hb, lease, mtu, notify, reserved = struct.unpack("<BBBBBBHHHHHHH", raw)
        if major != 1:
            raise ProtocolError(Detail.BAD_VERSION)
        if minor != 0 or reserved or features & ~31 or profiles & ~7 or patterns & ~31:
            raise ProtocolError(Detail.BAD_VALUE)
        return cls(features, profiles, patterns, strength, repeat, ttl, hb, lease, mtu, notify)


@dataclass(frozen=True)
class AudioFrame:
    profile: int
    stream: int
    seq: int
    sample_index: int
    body: bytes
    flags: int = 0

    def packets(self, mtu=247):
        if self.profile not in PROFILES or len(self.body) != PROFILES[self.profile][2]:
            raise ProtocolError(Detail.BAD_LENGTH)
        size = min(mtu - 3, 244) - 16
        if size < 1 or self.flags & ~31:
            raise ProtocolError(Detail.BAD_VALUE)
        return [AUDIO_HEADER.pack(1, 1, self.flags, self.profile, self.stream,
                                 self.seq, self.sample_index, len(self.body), offset)
                + self.body[offset:offset + size] for offset in range(0, len(self.body), size)]


def newer(value, old, bits):
    delta = (value - old) & ((1 << bits) - 1)
    return 0 < delta < (1 << (bits - 1))


class Reassembler:
    """Bounded, non-overlapping fragments. A new stream must be explicitly reset."""
    def __init__(self, limit=5, timeout_ms=100):
        self.limit, self.timeout = limit, timeout_ms
        self.reset()

    def reset(self, stream=None):
        self.stream, self.last_seq, self.last_sample = stream, None, None
        self.retired_seq = None
        self.pending = {}
        self.expired = 0
        self.lost = 0

    def push(self, packet, now_ms):
        for key, item in list(self.pending.items()):
            if now_ms - item[0] >= self.timeout:
                del self.pending[key]
                if self.retired_seq is None or newer(key,self.retired_seq,16):
                    self.retired_seq = key
                self.expired += 1
        if len(packet) <= 16 or len(packet) > 244:
            raise ProtocolError(Detail.BAD_LENGTH)
        v, kind, flags, profile, stream, seq, sample, total, offset = AUDIO_HEADER.unpack_from(packet)
        data = bytes(packet[16:])
        if v != 1:
            raise ProtocolError(Detail.BAD_VERSION)
        if kind != 1 or flags & ~31 or profile not in PROFILES:
            raise ProtocolError(Detail.BAD_VALUE)
        if total != PROFILES[profile][2] or offset + len(data) > total:
            raise ProtocolError(Detail.BAD_LENGTH)
        if self.stream is None:
            self.stream = stream
        if stream != self.stream:
            raise ProtocolError(Detail.BAD_VALUE, "unexpected stream; reset on STARTED")
        if self.last_seq is not None and not newer(seq, self.last_seq, 16):
            return None
        if self.retired_seq is not None and not newer(seq,self.retired_seq,16):
            return None
        if seq not in self.pending:
            if len(self.pending) >= self.limit:
                victim = min(self.pending, key=lambda k: self.pending[k][0])
                del self.pending[victim]
                if self.retired_seq is None or newer(victim,self.retired_seq,16):
                    self.retired_seq = victim
                self.expired += 1
            self.pending[seq] = (now_ms, (profile, sample, total, flags), {})
        created, meta, parts = self.pending[seq]
        if meta != (profile, sample, total, flags):
            del self.pending[seq]
            raise ProtocolError(Detail.BAD_VALUE, "fragment metadata mismatch")
        if offset in parts and parts[offset] == data:
            return None  # byte-identical retry
        if any(offset < pos + len(part) and pos < offset + len(data) for pos, part in parts.items()):
            del self.pending[seq]
            raise ProtocolError(Detail.BAD_VALUE, "overlapping fragments")
        parts[offset] = data
        if sum(map(len, parts.values())) != total:
            return None
        body = b"".join(parts[pos] for pos in sorted(parts))
        del self.pending[seq]
        if self.last_sample is not None and not newer(sample, self.last_sample, 32):
            return None
        if self.last_seq is not None:
            self.lost += ((seq - self.last_seq) & 65535) - 1
        self.last_seq, self.last_sample = seq, sample
        for key in list(self.pending):
            if not newer(key, seq, 16):
                del self.pending[key]
        return AudioFrame(profile, stream, seq, sample, body, flags)
