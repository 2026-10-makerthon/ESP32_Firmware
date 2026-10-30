"""Sample-clock gate and bounded audio queue, independent of BLE and microphones."""
from collections import deque
import math
import struct
from .codec import encode
from .protocol import AudioFrame, Flags, PROFILES


class SoundGate:
    def __init__(self, rate=16000, on=-4500, off=-5000, hold=500, pre=100):
        self.rate, self.on, self.off, self.hold, self.pre = rate, on, off, hold, pre
        self.window = deque(maxlen=rate // 100)
        self.samples = 0
        self.active = False
        self.quiet = 0
        self.level = -120.0

    def feed(self, samples):
        """Normalized, pre-gain samples in [-1,1]; returns any-start and any-end."""
        started = ended = False
        for value in samples:
            self.window.append(value)
            self.samples += 1
            if len(self.window) < self.window.maxlen or self.samples % (self.rate // 200):
                continue
            mean = sum(self.window) / len(self.window)
            power = max(0.0, sum(x*x for x in self.window) / len(self.window) - mean*mean)
            self.level = 10 * math.log10(max(power, 1e-12))
            if not self.active:
                if self.level * 100 + 1e-8 >= self.on:
                    self.active = started = True
                    self.quiet = 0
            elif self.level * 100 + 1e-8 >= self.off:
                self.quiet = 0
            else:
                self.quiet += 5
                if self.quiet >= self.hold:
                    self.active = False
                    ended = True
                    self.quiet = 0
        return started, ended


class AudioPipeline:
    def __init__(self, profile=1, stream=1, detection=(-4500,-5000,500,100), queue_limit=5):
        self.profile, self.stream = profile, stream
        self.rate, self.count, _ = PROFILES[profile]
        self.gate = SoundGate(self.rate, *detection)
        self.pre = deque(maxlen=detection[3] // 20)
        self.queue = deque()
        self.limit = queue_limit
        self.index = self.seq = self.dropped = 0
        self.last_selected = -1
        self.transmitting = False
        self.discontinuity = False

    def _append(self, samples, index, flags):
        body = struct.pack(f"<{len(samples)}h", *samples) if self.profile == 3 else encode(samples)
        frame = AudioFrame(self.profile, self.stream, self.seq & 65535, index & 0xffffffff, body, int(flags))
        self.seq += 1
        self.last_selected = index
        if len(self.queue) >= self.limit:
            # Drop old pre-roll first, otherwise oldest live audio.
            victim = next((f for f in self.queue if f.flags & Flags.PRE_ROLL), self.queue[0])
            position = self.queue.index(victim)
            self.queue.remove(victim)
            if victim.flags & Flags.BURST_START:
                if position < len(self.queue):
                    following = self.queue[position]
                    self.queue[position] = AudioFrame(following.profile, following.stream, following.seq,
                        following.sample_index, following.body, following.flags | Flags.BURST_START)
                else:
                    frame = AudioFrame(frame.profile, frame.stream, frame.seq, frame.sample_index,
                                       frame.body, frame.flags | Flags.BURST_START)
            self.dropped += 1
            self.discontinuity = True
        self.queue.append(frame)

    def feed(self, samples, motor_active=False, detection_samples=None):
        if len(samples) != self.count:
            raise ValueError(f"expected {self.count} PCM samples")
        normalized = detection_samples if detection_samples is not None else [x / 32768 for x in samples]
        if len(normalized) != self.count:
            raise ValueError("detection samples must match frame length")
        started, ended = self.gate.feed(normalized)
        motor_flag = Flags.MOTOR_ACTIVE if motor_active else 0
        if not self.transmitting and started:
            candidates = [(s, i, f | Flags.PRE_ROLL) for s, i, f in self.pre if i > self.last_selected]
            candidates.append((samples, self.index, motor_flag))
            for n, (s, i, flags) in enumerate(candidates):
                self._append(s, i, flags | (Flags.BURST_START if n == 0 else 0) |
                             (Flags.BURST_END if n == len(candidates)-1 and not self.gate.active else 0))
            self.transmitting = self.gate.active
        elif self.transmitting:
            self._append(samples, self.index, motor_flag | (Flags.BURST_END if not self.gate.active else 0))
            self.transmitting = self.gate.active
        self.pre.append((list(samples), self.index, motor_flag))
        self.index += self.count

    def pop(self):
        if not self.queue:
            return None
        frame = self.queue.popleft()
        if self.discontinuity:
            frame = AudioFrame(frame.profile, frame.stream, frame.seq, frame.sample_index,
                               frame.body, frame.flags | Flags.DISCONTINUITY)
            self.discontinuity = False
        return frame
