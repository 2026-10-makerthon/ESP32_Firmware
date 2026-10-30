"""Offline end-to-end demo using actual wire bytes and a fake device clock."""
import json
import math
from pathlib import Path
import struct
import wave
from .device import Device
from .protocol import Command, Op, Reassembler
from .codec import pcm


def run(output="build/demo"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    device = Device(simulation=True)
    device.audio_subscribed = device.event_subscribed = True
    commands = [Command(Op.GET_STATE,1,0), Command(Op.SET_DETECTION,2,1,(-4500,-5000,500,100)),
                Command(Op.START_AUDIO,3,1,(1,)), Command(Op.HEARTBEAT,4,1),
                Command(Op.PLAY_PATTERN,5,1,(2,80,1,0,2000))]
    rows, audio, receiver = [], [], Reassembler()
    for command in commands:
        raw = command.encode()
        rows.append({"kind":"control", "at_ms":0, "hex":raw.hex()})
        device.command(raw, 0)
    received = []
    for frame_no in range(150):
        now = frame_no * 20
        device.tick(now)
        # Silence, two sound bursts, and hold/silent gaps.
        amplitude = 6000 if (20 <= frame_no < 45 or 95 <= frame_no < 115) else 0
        samples = [int(amplitude * math.sin(2*math.pi*440*(frame_no*320+i)/16000)) for i in range(320)]
        device.capture(samples, now)
        while device.events:
            event = device.events.popleft()
            rows.append({"kind":"event", "at_ms":now, "hex":event.encode().hex()})
        while device.audio.queue:
            frame = device.audio.pop()
            for packet in frame.packets():
                rows.append({"kind":"audio", "at_ms":now, "hex":packet.hex()})
                decoded = receiver.push(packet, now)
                if decoded:
                    received.append(decoded)
    # Place samples on original timeline; zero-fill intentionally omitted intervals.
    audio = [0] * (150 * 320)
    for frame in received:
        audio[frame.sample_index:frame.sample_index+320] = pcm(frame)
    with wave.open(str(output / "received.wav"), "wb") as wav:
        wav.setparams((1,2,16000,0,"NONE","not compressed"))
        wav.writeframes(struct.pack(f"<{len(audio)}h", *audio))
    (output / "packets.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows), encoding="utf-8")
    summary = {"mode":"offline simulation; no radio or physical output", "frames":len(received),
               "protocol":"1.0", "sample_rate":16000, "channels":1,
               "capabilities_hex":device.capabilities().hex(),
               "lost_frames":receiver.lost, "queue_dropped":device.audio.dropped,
               "haptic_changes":device.driver.changes,
               "bursts":sum(bool(f.flags & 4) for f in received), "duration_s":3,
               "silence_gaps_are_zero_filled":True}
    (output / "summary.json").write_text(json.dumps(summary,indent=2), encoding="utf-8")
    return summary
