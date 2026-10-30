import importlib.util
from pathlib import Path
import json
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("hardware_header",ROOT/"scripts/hardware-header.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_unknown_profile_stays_disabled():
    profile=json.loads((ROOT/"hardware/profiles/unverified.json").read_text())
    assert "#define SH_HW_VERIFIED 0" in module.generate(profile)
    profile["haptic"]["enabled"]=True
    with pytest.raises(ValueError):module.generate(profile)


def test_physical_output_requires_all_reviewed_values():
    # Synthetic validation fixture, not a recommendation for any real module.
    h={"enabled":True,"backend":"pwm_module","control_gpio":1,"input_3v3_verified":True,
       "supply_voltage_v":3.3,"peak_current_ma":1,"pwm_frequency_hz":100,
       "weak_duty":100,"strong_duty":200,"verification_record":"test fixture; not hardware evidence"}
    assert "#define SH_HW_VERIFIED 1" in module.generate({"haptic":h})
    for key in ("supply_voltage_v","peak_current_ma","pwm_frequency_hz","weak_duty","strong_duty","verification_record"):
        bad=dict(h);bad[key]=None
        with pytest.raises(ValueError):module.generate({"haptic":bad})


def test_xiao_pins_and_unknown_motor_stay_disabled():
    profile=json.loads((ROOT/"hardware/profiles/xiao-inmp441-drv2605l.json").read_text())
    header=module.generate(profile)
    assert profile["i2s"]=={"bclk_gpio":2,"ws_gpio":1,"din_gpio":4,"selected_slot":"left"}
    assert profile["button"]["gpio"]==7
    assert "#define SH_HW_VERIFIED 0" in header
    assert "#define SH_HAPTIC_BACKEND_DRV2605 1" in header
    profile["haptic"]["enabled"]=True
    with pytest.raises(ValueError):module.generate(profile)


def test_drv_requires_reviewed_registers_and_signed_rtp():
    # Fictional validation fixture, not actuator settings for actual hardware.
    h={"backend":"drv2605l","enabled":True,"supply_voltage_v":3.3,"peak_current_ma":1,
       "motor_type":"ERM","motor_rated_voltage_v":1,"max_rtp":64,
       "registers":{f"{r:02x}":1 for r in range(0x16,0x1e)},
       "verification_record":"synthetic test fixture; not physical evidence"}
    assert "#define SH_HW_VERIFIED 1" in module.generate({"haptic":h})
    for key in ("motor_type","motor_rated_voltage_v","peak_current_ma","max_rtp","verification_record"):
        bad=dict(h);bad[key]=None
        with pytest.raises(ValueError):module.generate({"haptic":bad})
    for reg in h["registers"]:
        bad=dict(h,registers=dict(h["registers"]));bad["registers"][reg]=None
        with pytest.raises(ValueError):module.generate({"haptic":bad})
    for control in (8, 9, 255):
        bad=dict(h,registers=dict(h["registers"]));bad["registers"]["1d"]=control
        with pytest.raises(ValueError):module.generate({"haptic":bad})


def test_xiao_rejects_colliding_pins_and_wrong_microphone_slot():
    profile=json.loads((ROOT/"hardware/profiles/xiao-inmp441-drv2605l.json").read_text())
    profile["button"]["gpio"]=profile["i2s"]["bclk_gpio"]
    with pytest.raises(ValueError):module.generate(profile)
    profile["button"]["gpio"]=7
    profile["i2s"]["selected_slot"]="right"
    with pytest.raises(ValueError):module.generate(profile)


def test_dm161_prototype_calculates_3v_without_claiming_verification():
    profile=json.loads((ROOT/"hardware/profiles/xiao-dm161-3v-prototype.json").read_text())
    header=module.generate(profile)
    assert "#define SH_HW_OUTPUT_ENABLED 1\n" in header
    assert "#define SH_HW_PROTOTYPE 1\n" in header
    assert "#define SH_HW_VERIFIED 0\n" in header
    assert "#define SH_DRV_REG_17 138\n" in header
    assert "#define SH_DRV_REG_1B 19\n" in header  # startup boost disabled
    assert "#define SH_DRV_REG_1D 160\n" in header  # ERM open-loop, signed, supply compensation
    assert 138*0.02159 <= 3.0 < 139*0.02159
    for key,value in (("prototype",False),("motor_type","LRA"),("supply_voltage_v",5.0),
                      ("design_output_target_v",3.1),("motor_reported_current_ma",150),
                      ("configuration_record",None),("registers",{})):
        bad=json.loads(json.dumps(profile));bad["haptic"][key]=value
        with pytest.raises(ValueError):module.generate(bad)
