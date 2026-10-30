"""Validate hardware profiles; never invent motor voltage or calibration values."""
import json
import math
from pathlib import Path
import sys


def generate(profile):
    h = profile["haptic"]
    enabled = h.get("enabled",False)
    drv = h.get("backend") == "drv2605l"
    prototype = h.get("prototype", False)
    if type(prototype) is not bool or (prototype and (not enabled or not drv)):
        raise ValueError("prototype output requires an enabled DRV2605L profile")
    pins = []
    if "i2s" in profile:
        i2s = profile["i2s"]
        if i2s.get("selected_slot") != "left":
            raise ValueError("the INMP441 adapter currently requires the left slot")
        pins += [i2s.get(k) for k in ("bclk_gpio", "ws_gpio", "din_gpio")]
    if "button" in profile:
        if profile["button"].get("active_low") is not True:
            raise ValueError("the power button must connect to GND")
        pins.append(profile["button"].get("gpio"))
    if drv:
        pins += [h.get("sda_gpio", 5), h.get("scl_gpio", 6)]
    elif enabled:
        pins.append(h.get("control_gpio"))
    if any(type(pin) is not int or not 0 <= pin <= 48 for pin in pins) or len(set(pins)) != len(pins):
        raise ValueError("hardware pins must be valid, distinct GPIO integers")
    regs = {}
    if prototype:
        if h.get("motor_type") != "ERM" or h.get("drive_mode") != "erm_open_loop":
            raise ValueError("prototype output only supports ERM open-loop mode")
        supply = h.get("supply_voltage_v")
        target = h.get("design_output_target_v")
        current = h.get("motor_reported_current_ma")
        if type(supply) not in (int,float) or not 2 <= supply <= 3.3:
            raise ValueError("prototype supply must be 2..3.3 V")
        if type(target) not in (int,float) or not 0 < target <= min(supply,3.0):
            raise ValueError("prototype target must be <= supply and <= 3.0 V")
        if type(current) not in (int,float) or not 0 < current <= 100:
            raise ValueError("prototype requires reported motor current <= 100mA; not a peak-current rating")
        if not h.get("configuration_record") or "registers" in h:
            raise ValueError("record prototype assumptions; its registers are calculated, not overridden")
        # TI SLOS854D Eq.6: ERM open-loop average = 0.02159 * OD_CLAMP.
        # Round down. Calibration registers below are reset defaults, unused in open-loop.
        regs = {"16":math.floor(target/0.02118), "17":math.floor(target/0.02159),
                "18":0x0c, "19":0x6c, "1a":0x36, "1b":0x13, "1c":0xf5, "1d":0xa0}
    elif enabled and drv:
        for key in ("supply_voltage_v", "peak_current_ma", "motor_rated_voltage_v"):
            if type(h.get(key)) not in (int, float) or not 0 < h[key] <= 10000:
                raise ValueError(f"missing confirmed {key}")
        if not 2 <= h["supply_voltage_v"] <= 5.2:
            raise ValueError("DRV2605L supply must be 2..5.2 V")
        if h.get("motor_type") not in ("ERM", "LRA") or not h.get("verification_record"):
            raise ValueError("record the motor type, power, calibration and boot/stop tests")
        regs = h.get("registers", {})
        for reg in range(0x16, 0x1e):
            if type(regs.get(f"{reg:02x}")) is not int or not 0 <= regs[f"{reg:02x}"] <= 255:
                raise ValueError(f"missing confirmed register 0x{reg:02x}")
        if not regs["16"] or not regs["17"] or regs["1d"] & 8:
            raise ValueError("require nonzero voltage limits and signed RTP format")
        if bool(regs["1a"] & 128) != (h["motor_type"] == "LRA"):
            raise ValueError("feedback register does not match motor type")
        if type(h.get("max_rtp")) is not int or not 1 <= h["max_rtp"] <= 127:
            raise ValueError("confirmed max_rtp must be 1..127")
    elif enabled:
        if h.get("backend") != "pwm_module" or h.get("input_3v3_verified") is not True:
            raise ValueError("physical output requires a verified 3.3V-compatible PWM module")
        for key in ("supply_voltage_v","peak_current_ma","pwm_frequency_hz"):
            if not isinstance(h.get(key),(int,float)) or h[key] <= 0:
                raise ValueError(f"missing confirmed {key}")
        if not isinstance(h["pwm_frequency_hz"],int) or not isinstance(h.get("control_gpio"),int) or not 0 <= h["control_gpio"] <= 48:
            raise ValueError("PWM frequency and GPIO must be valid integers")
        if not all(isinstance(h.get(key),int) for key in ("weak_duty","strong_duty")) or not 1 <= h["weak_duty"] <= h["strong_duty"] <= 1023:
            raise ValueError("confirmed 10-bit PWM duties must satisfy 1 <= weak <= strong <= 1023")
        if not h.get("verification_record"):
            raise ValueError("record wiring, power, input compatibility, and measured duty calibration")
    values = {"SH_HW_VERIFIED":int(enabled and not prototype),
              "SH_HW_OUTPUT_ENABLED":int(enabled), "SH_HW_PROTOTYPE":int(prototype),
              "SH_HAPTIC_GPIO":h.get("control_gpio",1),
              "SH_HAPTIC_HZ":h["pwm_frequency_hz"] if enabled and not drv else 0,
              "SH_HAPTIC_WEAK_DUTY":h["weak_duty"] if enabled and not drv else 0,
              "SH_HAPTIC_STRONG_DUTY":h["strong_duty"] if enabled and not drv else 0,
              "SH_HAPTIC_BACKEND_DRV2605":int(drv),
              "SH_DRV_SDA":h.get("sda_gpio", 5), "SH_DRV_SCL":h.get("scl_gpio", 6),
              "SH_DRV_MAX_RTP":127 if prototype else h["max_rtp"] if enabled and drv else 0}
    for key in ("SH_DRV_SDA", "SH_DRV_SCL", "SH_HAPTIC_GPIO"):
        if type(values[key]) is not int or not 0 <= values[key] <= 48:
            raise ValueError(f"invalid {key}")
    if drv and values["SH_DRV_SDA"] == values["SH_DRV_SCL"]:
        raise ValueError("SDA and SCL must be different GPIOs")
    for reg in range(0x16, 0x1e):
        values[f"SH_DRV_REG_{reg:02X}"] = regs[f"{reg:02x}"] if enabled and drv else 0
    return "/* Generated from the selected hardware profile. */\n"+"".join(f"#define {k} {v}\n" for k,v in values.items())


if __name__=="__main__":
    profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(generate(profile),encoding="utf-8")
