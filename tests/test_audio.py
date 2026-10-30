import math
import pytest
from harness.audio import SoundGate, AudioPipeline
from harness.protocol import Flags


def alternating(amplitude,count=320):
    return [amplitude if i%2 else -amplitude for i in range(count)]


def test_exact_threshold_dc_and_hold():
    gate=SoundGate(on=-600,off=-1200,hold=20)
    amplitude=10**(-6/20)
    gate.feed([1.0]*320)
    assert not gate.active # DC is removed
    gate=SoundGate(on=-600,off=-1200,hold=20)
    start,_=gate.feed(alternating(amplitude))
    assert start and gate.active
    gate.feed(alternating(.3))
    assert gate.active # hysteresis: below on but above off
    gate.feed([0.0]*320)
    gate.feed([0.0]*320)
    assert not gate.active


@pytest.mark.parametrize("pre",[0,100])
def test_bursts_pre_roll_and_no_duplicate(pre):
    pipe=AudioPipeline(detection=(-4500,-5000,0,pre))
    frames=[]
    for n in range(40):
        samples=alternating(6000) if n in (10,11,15,16) else [0]*320
        pipe.feed(samples,motor_active=n==10)
        while pipe.queue:frames.append(pipe.pop())
    assert sum(bool(f.flags&Flags.BURST_START) for f in frames)==2
    assert sum(bool(f.flags&Flags.BURST_END) for f in frames)==2
    indices=[f.sample_index for f in frames]
    assert len(indices)==len(set(indices)) and indices==sorted(indices)
    assert any(f.flags&Flags.MOTOR_ACTIVE for f in frames)
    assert any(f.flags&Flags.PRE_ROLL for f in frames)==bool(pre)


def test_continuous_and_queue_congestion():
    pipe=AudioPipeline()
    for _ in range(100):pipe.feed(alternating(6000))
    assert pipe.transmitting and pipe.gate.active
    assert len(pipe.queue)==5 and pipe.dropped==95
    latest=[]
    while pipe.queue:latest.append(pipe.pop())
    assert latest[0].flags&Flags.DISCONTINUITY
    assert latest[-1].sample_index==99*320


def test_short_impulse_and_full_hold():
    pipe=AudioPipeline()
    impulse=[0]*320;impulse[160]=32767
    pipe.feed(impulse)
    assert pipe.transmitting
    for _ in range(24):pipe.feed([0]*320)
    assert pipe.transmitting
    for _ in range(2):pipe.feed([0]*320)
    assert not pipe.transmitting


def test_pre_gain_detection_separate_from_output_gain():
    pipe=AudioPipeline()
    pipe.feed(alternating(20000),detection_samples=alternating(.00001))
    assert not pipe.transmitting
