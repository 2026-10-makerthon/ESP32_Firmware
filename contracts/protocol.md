# Sound/Haptic BLE Protocol 1.0

Status: frozen integration contract, 2026-10-29. This file is normative. The earlier Korean design documents are background. Implementations and hardware verification status are in `docs/STATUS.ko.md`. Breaking wire changes require a new major version; capability changes must be negotiated. All multi-byte integers are little-endian, signed integers are two's complement, sizes are bytes. No HTTP service is implied.

## 1. Roles and GATT

The device is a BLE peripheral/GATT server. The phone or PC is a central/GATT client. One central is supported. The peer must implement the custom audio decoder; this service is not a system Bluetooth microphone or standard LE Audio profile.

| Role | UUID | Property |
|---|---|---|
| Service | `8e1f0000-6f5a-4d7c-a321-9b7e2c1048d0` | primary |
| Audio | `8e1f0001-6f5a-4d7c-a321-9b7e2c1048d0` | Notify, device to client |
| Control | `8e1f0002-6f5a-4d7c-a321-9b7e2c1048d0` | Write with response, client to device |
| Event | `8e1f0003-6f5a-4d7c-a321-9b7e2c1048d0` | Indicate, execution results |
| Capabilities | `8e1f0004-6f5a-4d7c-a321-9b7e2c1048d0` | Read, 20 bytes |

Discovery uses the service UUID rather than the display name. The XIAO firmware (2026-10-30) uses persistent single-peer BLE Secure Connections Just Works bonding. A six-second startup hold clears the previous bond and opens a 120-second enrollment window. Normal startup accepts only the saved peer. Complete 128-bit link encryption and bonding before accessing the application interface; Capabilities and Control require encryption, and application subscriptions/notifications are gated by authorization. Just Works does not provide MITM authentication. UUIDs and all v1 packet bytes remain unchanged. See `docs/XIAO_OPERATION.ko.md` for the button and client pairing flow.

## 2. Connection lifecycle

1. Connect, complete pairing/encryption (or restore the existing bond), and discover services. Read Capabilities; reject unsupported major versions.
2. Subscribe to Event **indications**.
3. Send GET_STATE with session_id=0; take the nonzero current session_id from its Event header.
4. Arrange/observe MTU negotiation, then check the actual result. Audio requires ATT_MTU >=185. PC backends may negotiate automatically and may not expose an MTU request API. A requested MTU/PHY is not a guaranteed result.
5. Subscribe to Audio notifications.
6. SET_DETECTION, then START_AUDIO(profile=1). Wait for ACCEPTED and then STARTED. STARTED supplies the actual capture epoch of the first collected frame, even when that frame is silent.
7. Sound above the threshold starts a burst automatically. Sustained sound continues streaming; no START_AUDIO per burst is needed.
8. Send HEARTBEAT every 500ms while using haptics. Obtain a successful heartbeat before PLAY_PATTERN.
9. To change detection: STOP_AUDIO -> SET_DETECTION -> START_AUDIO. To replace a pattern: STOP_HAPTIC -> wait for STOPPED -> PLAY_PATTERN.
10. On disconnect discard pending fragments and playback buffers. Reconnect with a new session, subscribe, configure, and arm again. Old audio/commands are never replayed into the new session.

Serialize response-requiring GATT operations. A successful ATT write only means the bytes reached the GATT server. Correlate Event.opcode and command_id to confirm execution. The client must keep callbacks short and use bounded audio queues. Link loss cannot deliver live audio; offline recording/retransmission is not provided.

## 3. Capabilities (20 bytes)

| Offset | Type | Meaning / v1 value |
|---|---|---|
| 0 | u8 | major=1 |
| 1 | u8 | minor=0 |
| 2 | u8 | feature bits: 0 physical haptic verified, 1 sound gate, 2 heartbeat lease, 3 fragmentation, 4 simulated audio and/or haptics |
| 3 | u8 | profiles bitmask; bit ID-1, currently 0x07 |
| 4 | u8 | patterns bitmask; bit ID-1, currently 0x1f |
| 5 | u8 | max_strength=100 |
| 6 | u16 | max_repeat=10 |
| 8 | u16 | max_ttl_ms=5000 |
| 10 | u16 | heartbeat_interval_ms=500 |
| 12 | u16 | heartbeat_lease_ms=1500 |
| 14 | u16 | minimum_audio_mtu=185 |
| 16 | u16 | maximum_notification_value=244 |
| 18 | u16 | reserved=0 |

Unknown feature bits or reserved values must not be silently assumed to have v1 behavior. A simulation bit is not evidence of physical output. Physical calibration is represented only by feature bit0. Default firmware is synthetic audio + log-only haptics (feature bits 0x1e).

Local bench-build exception (2026-10-31): an explicitly selected `prototype` hardware profile may enable uncalibrated physical ERM output while verification bit0 remains clear. This permission is local firmware configuration and cannot be enabled by a BLE command. The DM161 3V prototype build uses feature bits 0x0e with a real microphone. A clear verification bit means unverified, not a guarantee of no physical output. UUIDs, packet formats, opcode values, and all timeout/STOP rules are unchanged. General builds retain the rejection rule below.

## 4. Control

Common 8-byte header: `version:u8=1, opcode:u8, command_id:u16, session_id:u32`. Commands are at most 20 bytes. Unsupported version/opcode, extra bytes, bad ranges and nonzero reserved values are rejected before any state change. If the transport cannot read an 8-byte header it reports an ATT length error, without trying to invent a correlated Event.

| Opcode | Command | Payload |
|---|---|---|
| 0x01 | GET_STATE | none; only command allowing session_id=0 |
| 0x02 | START_AUDIO | profile_id:u8 (1,2,3) |
| 0x03 | STOP_AUDIO | none; disarms and discards pending audio/pre-roll |
| 0x04 | SET_DETECTION | on_dbfs_x100:i16, off_dbfs_x100:i16, hold_ms:u16, pre_roll_ms:u16 |
| 0x10 | PLAY_PATTERN | pattern_id:u8, strength:u8, repeat:u8, reserved:u8=0, ttl_ms:u16 |
| 0x11 | STOP_HAPTIC | none; stops the current pattern |
| 0x20 | HEARTBEAT | none; renews the lease; never resumes a stopped pattern |

Detection range: both thresholds -9000..0, off <= on-300, hold 0..5000ms, pre-roll 0..100ms in multiples of 20ms. Initial settings are -4500,-5000,500,100. Change only while disarmed. Thresholds are dBFS, not calibrated physical dB SPL.

PLAY ranges: pattern 1..5, strength 1..100, repeat 1..10, ttl 1..5000ms. Entire duration including 200ms between repetitions must fit TTL, otherwise BAD_VALUE. One active pattern only; a new PLAY returns BUSY. Strength is a logical percentage, not voltage or guaranteed acceleration. Unverified physical hardware returns HARDWARE_UNVERIFIED unless the explicit local prototype permission described above is selected; explicitly simulated devices may accept the command without energizing a GPIO.

### Sessions, replay, overload

Each connection gets a new nonzero session_id; all commands other than initial GET_STATE must match it. For execution/configuration commands, retain active commands and up to 64 recent command records for 60 seconds. During retention, same ID + exact bytes returns the latest result without replaying the effect. Same ID + different bytes returns COMMAND_ID_CONFLICT. Expired inactive entries can be reclaimed. If all 64 entries are retained, new execution/configuration commands return CACHE_FULL rather than evicting protected records. Clients should use new IDs and reconnect before u16 ID exhaustion; the supplied client never wraps command IDs.

**Resolved v1 clarification:** HEARTBEAT has a dedicated path outside that execution cache. Every valid heartbeat receipt first checks expiry, then renews the lease and returns COMPLETED; repeating a heartbeat may renew the lease but cannot revive an expired pattern. Otherwise the required 500ms heartbeats would fill 64 cache slots in 32 seconds. Do not reuse a retained execution command's ID for a heartbeat. This is the only repeat-receipt exception. STOP_HAPTIC and STOP_AUDIO also retain a cache-independent processing path when the cache is full; uncached STOP retries are naturally idempotent.

STOP processing never waits for an audio/Event transmission. A 5ms scheduler checks deadlines without replaying missed ticks. Finite Event queues that overflow force haptics OFF; the firmware terminates the connection so the client must establish a fresh session. All queues are bounded. Physical output must be OFF on boot/error/disconnect/STOP/lease expiry. A heartbeat delayed until after the 1500ms lease cannot restart the previous pattern.

## 5. Events

8-byte header identical to Control, with the original opcode/command_id and the **current** session_id. Body: `status:u8, detail:u8, device_ms:u32`. device_ms is a wrapping u32 monotonic millisecond clock.

Status: ACCEPTED=1, STARTED=2, COMPLETED=3, STOPPED=4, REJECTED=5.

| Event | Additional body after device_ms | Total |
|---|---|---|
| successful GET_STATE | stream_id:u16, state_flags:u8, profile_id:u8 | 18 |
| START_AUDIO STARTED | stream_id:u16, capture_epoch_ms:u32 | 20 |
| all others, including rejected GET_STATE | none | 14 |

State bits: 0 ARMED, 1 TRANSMITTING, 2 HAPTIC_RUNNING, 3 HARDWARE_VERIFIED, 4 AUDIO_SUBSCRIBED, 5 EVENT_SUBSCRIBED. Remaining bits are zero. Disarmed GET_STATE profile_id=0. stream_id may be zero before the first START.

GET_STATE/SET_DETECTION/HEARTBEAT return COMPLETED. START_AUDIO returns ACCEPTED, followed by STARTED once the first frame is captured (not when the first loud sound occurs). PLAY_PATTERN returns STARTED then COMPLETED, or STOPPED if interrupted. STOP_HAPTIC returns STOPPED for its own command ID and also updates the interrupted PLAY command with STOPPED. STOP_AUDIO similarly updates its active START command. Rejected commands return REJECTED with no command-specific extra fields.

| detail | Name |
|---|---|
| 0 | OK |
| 1 | BAD_LENGTH |
| 2 | BAD_VERSION |
| 3 | BAD_VALUE |
| 4 | BUSY |
| 5 | SESSION_MISMATCH |
| 6 | HARDWARE_UNVERIFIED |
| 7 | MTU_TOO_SMALL |
| 8 | INTERNAL |
| 9 | UNKNOWN_OPCODE |
| 10 | COMMAND_ID_CONFLICT |
| 11 | NOT_SUBSCRIBED |
| 12 | LEASE_EXPIRED |
| 13 | TTL_EXPIRED |
| 14 | CACHE_FULL |

## 6. Audio

| Profile | Rate | Channels | Samples/frame | Body bytes |
|---|---|---|---|---|
| 1 | 16000Hz | mono | 320 (20ms) | 164, independent IMA ADPCM4 |
| 2 | 8000Hz | mono | 160 (20ms) | 84, independent IMA ADPCM4 |
| 3 | 16000Hz | mono | 320 (20ms) | 640, signed PCM16 LE |

Every notification fragment starts with this 16-byte header:

| Offset | Type | Field |
|---|---|---|
| 0 | u8 | version=1 |
| 1 | u8 | kind=1 |
| 2 | u8 | flags |
| 3 | u8 | profile_id |
| 4 | u16 | stream_id, increments on START, wraps |
| 6 | u16 | frame_seq, assigned only to selected frames, wraps |
| 8 | u32 | first_sample_index relative to this stream's capture epoch, wraps |
| 12 | u16 | complete frame body bytes |
| 14 | u16 | fragment_offset within that body |

Flags: bit0 MOTOR_ACTIVE, bit1 DISCONTINUITY, bit2 BURST_START, bit3 BURST_END, bit4 PRE_ROLL; other bits zero. MOTOR_ACTIVE represents the driver output during capture, including a simulated driver in simulation mode. Frames may contain both START and END for a short isolated sound. Fragment metadata and flags must match across a frame.

Maximum fragment body = `min(ATT_MTU-3,244)-16`. At MTU185 a 164-byte block fits one notification (180-byte value). Fragmentation at MTU23 is covered by offline tests, but live streaming below185 is rejected. Profile1 continuous traffic is 50 notifications/s, 9000B/s=72kbps before BLE overhead. Profile3 needs multiple fragments and actual throughput validation.

Reassembly key: connection generation + stream_id + frame_seq. Reject out-of-bounds offset/length, mismatched metadata, unexpected stream, and overlapping fragments; byte-identical duplicate fragments are ignored. Support at most five incomplete frames; discard incomplete frames after100ms. A new STARTED/reconnect explicitly resets the receiver. Once a newer complete frame is delivered, never deliver an older one. Compare sequence/sample counters using modular half-range arithmetic. No live audio retransmission is provided.

### Independent ADPCM body

Bytes0..1: first PCM sample/predictor, signed16 LE. Byte2: initial IMA step index0..88. Byte3: reserved0. Subsequent samples use the standard 89-entry IMA step table and index deltas [-1,-1,-1,-1,2,4,6,8]; **low nibble first**. Saturate predictor to signed16 and index to0..88 after each code. For320 samples, encode319 nibbles into160 bytes, last high nibble=0 padding. For160 samples, encode159 nibbles into80 bytes, same padding. Decode only the declared sample count. Blocks are independent; do not carry predictor/index between blocks. This is not a WAV IMA or RTP DVI4 container. Compression is lossy.

Use `golden_vectors.json` to compare **decoded PCM with reference decoded PCM**, not with the uncompressed input. Vectors were generated by CPython3.12's independent audioop C implementation, with nibble packing adapted, plus a manually checked minimal vector: initial0/index0, codes1,2,3,4 -> samples0,1,4,8,15 -> body `000000002143`.

### Gate, time, gaps, queues

The capture adapter continuously samples. For detection, use pre-gain/AGC normalized microphone values. Remove each10ms window's mean, compute RMS/dBFS, evaluate every5ms. A single window >=on starts transmission; continue while >=off; end after hold_ms continuously below off, at a20ms frame boundary. Software comparisons allow a negligible1e-8 in dBFS*100 for floating point equality. This is amplitude detection, not voice-only VAD or a promise to detect every peak.

Keep up to100ms of completed frames as pre-roll, separate from a five-frame transmit queue. Preserve continuous sample_index while quiet, but do not assign frame_seq to intentionally omitted frames. Thus a sample_index jump at BURST_START is not radio loss; a frame_seq gap is selected audio that was dropped/lost. Do not resend pre-roll already selected for an earlier burst. Flush old client playback buffers on BURST_START; use the index/flags for gaps, not indefinite waiting.

If the transmit queue fills, drop old pre-roll first, otherwise the oldest live frame, set DISCONTINUITY on the next transmitted frame, and carry an unsent BURST_START marker to the first retained frame of that burst. Six initial frames (100ms pre-roll+20ms current) may exceed the five-frame queue: this intentionally favors current audio and can discard the oldest pre-roll. MOTOR_ACTIVE audio is still sent; analysis-triggered haptics need an external cooldown/self-vibration policy.

`capture_epoch_ms + first_sample_index/sample_rate*1000` estimates device capture time, with u32 unwrapping. Do not subtract independent PC/device clocks directly. Use command roundtrip time to estimate clock offset and uncertainty, or external instrumentation. The included client records host/device timestamps but does not claim measured end-to-end latency. The I2S adapter's completion-minus20ms timestamp is an estimate affected by DMA backlog; actual capture latency is unverified.

## 7. Patterns

`patterns.json` is the canonical segment table; each [duration_ms,relative_strength_percent] applies for a half-open interval. Output strength = floor((requested_strength*relative_strength+50)/100). RAMP has200 consecutive5ms segments, relative strength=floor(i*100/199), i=0..199. Always OFF at completion. SINGLE200ms, DOUBLE150ON/150OFF/150ON, LONG700ms, RAMP1000ms, SOS3240ms. SOS has120/360ms pulses,120ms inner gaps,360ms group gaps. Repetitions have200ms OFF between them, never after the final repetition. TTL is measured from command receipt. Missed ticks evaluate current time rather than replaying old pulses.

## 8. Examples

These examples assume the session from GET_STATE is0x12345678. Never hard-code that session for a real connection.

```text
GET_STATE, id1, initial session0:
01 01 01 00 00 00 00 00
SET_DETECTION, id2, -45/-50dBFS, hold500, pre100:
01 04 02 00 78 56 34 12 6c ee 78 ec f4 01 64 00
START_AUDIO, id3, profile1:
01 02 03 00 78 56 34 12 01
HEARTBEAT, id4:
01 20 04 00 78 56 34 12
PLAY DOUBLE, id5, strength80, repeat1, ttl2000:
01 10 05 00 78 56 34 12 02 50 01 00 d0 07
STOP_HAPTIC, id6:
01 11 06 00 78 56 34 12
```

Full offline Control/Event/Audio examples are generated with `python -m harness demo`. See `examples/packets.jsonl`, `examples/received.wav`, and `examples/summary.json` in the developer handoff package. UUID/opcode/byte-order changes require explicit versioning and matching changes to both C/Python and fixed vectors.
