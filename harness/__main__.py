import argparse
import asyncio
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Sound/haptic protocol v1 development tools")
    subs = parser.add_subparsers(dest="action",required=True)
    demo = subs.add_parser("demo",help="offline wire-format demo; no BLE hardware needed")
    demo.add_argument("--output",default="build/demo")
    verify = subs.add_parser("verify")
    verify.add_argument("--gate",choices=["contract","faults","builds","all"],default="all")
    scan = subs.add_parser("scan",help="scan for matching BLE service")
    scan.add_argument("--seconds",type=float,default=5)
    ble = subs.add_parser("hil",help="capture from an explicitly named BLE device")
    ble.add_argument("--device",required=True)
    ble.add_argument("--duration",type=float,default=10)
    ble.add_argument("--play",type=int,choices=range(1,6))
    ble.add_argument("--pair",action="store_true",help="pair/bond during the physical 6-second startup window")
    ble.add_argument("--output",default="build/ble")
    args = parser.parse_args()
    if args.action == "demo":
        from .demo import run
        print(json.dumps(run(args.output),indent=2))
        return 0
    if args.action == "scan":
        from .ble_client import scan
        print(json.dumps(asyncio.run(scan(args.seconds)),ensure_ascii=False,indent=2))
        return 0
    if args.action == "hil":
        from .ble_client import Client
        print(json.dumps(asyncio.run(Client(args.device,args.output,pair=args.pair).capture(args.duration,args.play)),indent=2))
        return 0
    report_dir = ROOT / "harness/reports"
    report_dir.mkdir(parents=True,exist_ok=True)
    selected = {"contract":["tests/test_protocol.py","tests/test_codec.py"],
                "faults":["tests/test_device.py","tests/test_audio.py","tests/test_client.py","tests/test_hardware.py"],
                "builds":["tests/test_native.py","tests/test_button.py","tests/test_link.py","tests/test_drv2605.py"], "all":["tests"]}[args.gate]
    start = time.monotonic()
    (ROOT / ".tools/tmp").mkdir(parents=True,exist_ok=True)
    (ROOT / "build").mkdir(exist_ok=True)
    env = dict(os.environ,TMP=str(ROOT / ".tools/tmp"),TEMP=str(ROOT / ".tools/tmp"),
               PYTHONUTF8="1",PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable,"-m","pytest","-q",*selected,
                             f"--junitxml={report_dir / (args.gate + '.xml')}",
                             f"--basetemp={ROOT / 'build/pytest-tmp'}"],cwd=ROOT,env=env,text=True,
                            encoding="utf-8",errors="replace",capture_output=True)
    print(result.stdout)
    print(result.stderr,end="")
    report = {"gate":args.gate,"exit_code":result.returncode,"passed":result.returncode==0,
              "duration_s":round(time.monotonic()-start,3),"python":sys.version,"os":platform.platform(),
              "scope":"offline Python and native C; does not build ESP-IDF (use scripts/build-firmware.ps1)",
              "hardware_verified":False,"android_verified":False,"stdout":result.stdout,"stderr":result.stderr}
    (report_dir / f"{args.gate}_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
