import pytest
from harness.device import Device
from harness.protocol import Command, Op, Status, Detail
from harness.patterns import duration


def command(d,op,cid,args=(),now=0,session=None):
    return d.command(Command(op,cid,d.session if session is None else session,args).encode(),now)


def ready(simulation=True):
    d=Device(simulation=simulation)
    d.event_subscribed=d.audio_subscribed=True
    return d


@pytest.mark.parametrize("pattern",range(1,6))
def test_patterns_finish_off(pattern):
    d=ready()
    e=command(d,Op.PLAY_PATTERN,1,(pattern,80,1,0,5000))
    assert e.status==Status.STARTED
    for now in range(0,duration(pattern)+5,5):
        if now%500==0:command(d,Op.HEARTBEAT,2+now//500,now=now)
        d.tick(now)
    assert d.driver.level==0 and d.playing is None
    assert d.cache[1][1].status==Status.COMPLETED


def test_duplicate_busy_conflict_stop_and_old_session():
    d=ready()
    raw=Command(Op.PLAY_PATTERN,1,1,(2,80,1,0,2000)).encode()
    d.command(raw,0)
    d.tick(150)
    assert d.driver.level==0
    assert d.command(raw,160).status==Status.STARTED
    assert d.driver.level==0 # retry did not restart
    assert command(d,Op.PLAY_PATTERN,2,(1,50,1,0,1000),now=170).detail==Detail.BUSY
    assert command(d,Op.PLAY_PATTERN,1,(1,50,1,0,1000),now=170).detail==Detail.COMMAND_ID_CONFLICT
    command(d,Op.STOP_HAPTIC,3,now=175)
    assert d.driver.level==0 and not d.playing
    d.connect(2,200)
    assert command(d,Op.PLAY_PATTERN,4,(1,50,1,0,1000),session=1).detail==Detail.SESSION_MISMATCH


def test_cache_saturation_does_not_block_stop_or_heartbeat():
    d=ready()
    command(d,Op.PLAY_PATTERN,0,(3,80,1,0,1000))
    for cid in range(1,64):command(d,Op.GET_STATE,cid)
    assert len(d.cache)==64
    assert command(d,Op.GET_STATE,100).detail==Detail.CACHE_FULL
    assert command(d,Op.HEARTBEAT,101,now=100).status==Status.COMPLETED
    assert command(d,Op.STOP_HAPTIC,102,now=100).status==Status.STOPPED
    assert not d.playing and d.driver.level==0


def test_lease_wrap_disconnect_unverified_and_validation():
    d=ready()
    command(d,Op.HEARTBEAT,1,now=0xffffff00)
    command(d,Op.PLAY_PATTERN,2,(5,80,1,0,5000),now=0xffffff00)
    d.tick((0xffffff00+1500)&0xffffffff)
    assert not d.playing and d.driver.level==0
    command(d,Op.HEARTBEAT,3,now=1300)
    assert not d.playing
    d.disconnect(1400)
    assert not d.cache and d.driver.level==0
    u=ready(False)
    assert command(u,Op.PLAY_PATTERN,1,(1,80,1,0,1000)).detail==Detail.HARDWARE_UNVERIFIED
    assert command(d,Op.SET_DETECTION,4,(-4500,-5000,500,100)).detail==Detail.NOT_SUBSCRIBED


def test_arming_capture_epoch_mtu_and_configuration():
    d=ready()
    d.mtu=23
    assert command(d,Op.START_AUDIO,1,(1,)).detail==Detail.MTU_TOO_SMALL
    d.mtu=247
    assert command(d,Op.START_AUDIO,2,(1,),now=100).status==Status.ACCEPTED
    assert d.capture_epoch is None
    d.capture([0]*320,120)
    assert d.capture_epoch==120 and d.cache[2][1].status==Status.STARTED
    assert command(d,Op.SET_DETECTION,3,(-4500,-5000,500,100)).detail==Detail.BUSY
    command(d,Op.STOP_AUDIO,4)
    assert command(d,Op.SET_DETECTION,5,(-4500,-5000,500,100)).status==Status.COMPLETED


def test_invalid_commands_do_not_change_output_and_ttl_rejected():
    d=ready()
    assert command(d,Op.PLAY_PATTERN,1,(5,80,2,0,1000)).detail==Detail.BAD_VALUE
    assert not d.playing and d.driver.level==0
    raw=bytearray(Command(Op.PLAY_PATTERN,2,1,(1,80,1,0,1000)).encode());raw[11]=1
    assert d.command(raw).detail==Detail.BAD_VALUE
    assert not d.playing


def test_command_expiry_and_event_backpressure():
    d=ready()
    command(d,Op.GET_STATE,1)
    command(d,Op.GET_STATE,2,now=60000)
    assert 1 not in d.cache
    command(d,Op.HEARTBEAT,3,now=60000)
    command(d,Op.PLAY_PATTERN,4,(3,80,1,0,1000),now=60000)
    for _ in range(130):command(d,Op.GET_STATE,5,now=60000)
    assert len(d.events)<=128 and not d.playing and d.driver.level==0


def test_removing_subscription_disarms_and_stops_haptic():
    d=ready()
    command(d,Op.START_AUDIO,1,(1,))
    command(d,Op.PLAY_PATTERN,2,(3,80,1,0,1000))
    d.transport(247,True,False,now=10)
    assert not d.audio and not d.playing and d.driver.level==0


def test_30_minute_heartbeat_does_not_exhaust_execution_cache():
    d=ready()
    for step in range(3600):
        now=step*500
        assert command(d,Op.HEARTBEAT,step+1,now=now).status==Status.COMPLETED
        if step%20==0:
            assert command(d,Op.PLAY_PATTERN,10000+step,(1,80,1,0,1000),now=now).status==Status.STARTED
        d.tick(now+250)
        d.events.clear()
    assert len(d.cache)==6 and d.driver.level==0 # one PLAY per10s,60s retention
