"""Package an already-built DM161 prototype firmware; never connect or flash."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True, help="staged ESP-IDF firmware project")
    args = parser.parse_args()
    stage = args.stage
    built = ROOT / "build/firmware-mic-physical"
    log = (ROOT / ".tools/firmware-dm161-3v-build.log").read_text(encoding="utf-8", errors="replace")
    if "Built successfully:" not in log:
        raise RuntimeError("a successful physical firmware build log is required")
    spec = importlib.util.spec_from_file_location("hardware_header", ROOT / "scripts/hardware-header.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profile_path = ROOT / "hardware/profiles/xiao-dm161-3v-prototype.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    header = module.generate(profile)
    if header != (stage / "main/hardware_profile.h").read_text(encoding="utf-8"):
        raise RuntimeError("build used a different hardware profile")
    sources = {}
    for path in (ROOT / "firmware").rglob("*"):
        if not path.is_file() or path.name == "hardware_profile.h":
            continue
        if path.suffix in (".c", ".h") or path.name in ("CMakeLists.txt", "Kconfig.projbuild"):
            relative = path.relative_to(ROOT / "firmware")
            if path.read_bytes() != (stage / relative).read_bytes():
                raise RuntimeError(f"source does not match the compiled staging tree: {relative}")
            sources[relative.as_posix()] = sha(path)
    config = (stage / "sdkconfig").read_text(encoding="utf-8")
    for setting in ("# CONFIG_SH_SIMULATED_HAPTIC is not set", "# CONFIG_SH_SYNTHETIC_AUDIO is not set"):
        if setting not in config:
            raise RuntimeError("expected real microphone and physical haptic configuration")
    flash = json.loads((built / "flasher_args.json").read_text())
    if flash["extra_esptool_args"]["chip"] != "esp32s3":
        raise RuntimeError("wrong target")
    files = {name: built / name for name in flash["flash_files"].values()}
    files["flasher_args.json"] = built / "flasher_args.json"
    for name, path in files.items():
        if sha(path) != sha(stage / "build" / name):
            raise RuntimeError(f"artifact does not match the successful build: {name}")
    tests = json.loads((ROOT / "harness/reports/all_report.json").read_text())
    if not tests["passed"]:
        raise RuntimeError("the latest offline verification failed")
    report = {
        "date": "2026-10-31", "esp_idf": "v5.5.1", "target": "esp32s3",
        "build_passed": True, "hardware_verified": False, "android_verified": False,
        "prototype_physical_output": True, "motor_type_assumption": "DC ERM",
        "supply_v": 3.3, "target_v": 3.0, "nominal_open_loop_average_v": 138 * 0.02159,
        "od_clamp": 138, "startup_boost": False, "max_rtp": 127,
        "capabilities_features": 14, "profile": profile_path.relative_to(ROOT).as_posix(),
        "binary_bytes": files["sound_haptic.bin"].stat().st_size,
        "binary_sha256": sha(files["sound_haptic.bin"]), "source_sha256": sources,
        "flash_sha256": {name: sha(files[name]) for name in flash["flash_files"].values()},
        "offline_test_result": tests["stdout"],
        "limitations": "No board flashing, motor voltage/current/start/stop, physical BLE, or phone testing. 80mA is user reported, not an established peak limit. Nominal voltage is not a measured or instantaneous maximum."
    }
    (ROOT / "harness/reports/dm161_3v_firmware_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    flash_args = flash["write_flash_args"][:]
    for offset, name in sorted(flash["flash_files"].items(), key=lambda entry: int(entry[0], 16)):
        flash_args.extend((offset, name))
    readme = """# DM161 3V 초기 출력용 펌웨어

XIAO ESP32-S3 + INMP441 + DRV2605L. 실제 마이크·실제 진동 출력 활성 빌드입니다.
DM161을 DC ERM으로 가정합니다. 전원3.3V, 명목 평균 구동값 약2.98V,
startup boost OFF입니다. 실제 출력·전류·기동·진동·무선 동작은 미검증입니다.
80mA는 제공 사양이며 전류 제한값이 아닙니다. Capabilities 검증 bit는0입니다.

꺼짐에서3~6초 누른 뒤 놓으면 켜짐,6초 유지하면 새 기기 페어링,
켜진 동안3초 누르면 꺼집니다. 꺼짐은 배터리 차단이 아닌 딥슬립입니다.
최초 등록은6초 동작 후2분 내에 합니다. 기존 등록 키는 삭제됩니다.
클라이언트는 기존 BLE 계약대로 연결·구독·설정·arm하고 heartbeat를 유지합니다.

다른 Windows PC에서 업로드 (ESP-IDF/Arduino IDE 설치 불필요):
1. ZIP 전체를 복사하고 압축을 풉니다. ZIP 안에서 직접 실행하지 마세요.
2. https://www.python.org/downloads/windows/ 에서 Python3.12를 설치합니다.
3. 압축을 푼 폴더를 열고 주소 표시줄에 powershell을 입력하여 실행합니다.
4. 최초 한 번 아래를 실행합니다 (인터넷 연결 필요).

    py -3 -m pip install "esptool==4.12.0"

5. 데이터 USB로 보드를 연결합니다. 보드의 BOOT을 누른 채 RESET을 한 번
   누르고 BOOT을 놓습니다. 장치 관리자 또는 아래 명령으로 포트를 확인합니다.

    py -3 upload.py --list-ports

6. COM5를 실제 보드의 포트로 바꿔 실행합니다. 이 명령이 실제 업로드입니다.

    py -3 upload.py --port COM5

py 명령이 없으면 설치한 Python이 PATH에 등록되었는지 확인하고,
위 명령들의 'py -3' 대신 'python'을 사용합니다.
파일만 확인하려면 'py -3 upload.py --check'를 실행합니다. 이 모드는 쓰지 않습니다.
업로드 스크립트는 실행 위치에 관계없이 자신의 폴더에서 세 바이너리를 찾고,
칩 종류·주소·파일 해시를 검사합니다. 실제 포트를 지정하기 전에는 쓰지 않습니다.
COM 포트가 없으면 데이터 케이블과 BOOT/RESET 조작을 확인하세요.
포트 사용 중 오류는 시리얼 모니터 등 해당 포트를 사용하는 프로그램을 닫고 재시도합니다.

핀·BLE 계약·상세 사용법은 XIAO_OPERATION.ko.md와 protocol.md를 읽으세요.
도구 설치: https://docs.espressif.com/projects/esptool/en/release-v4/esp32s3/installation.html
보드 BOOT 모드: https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/#bootloader-mode
"""
    output = ROOT / "dist/dm161-3v-prototype-esp32s3.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in files.items():
            archive.write(path, name)
        archive.write(profile_path, "hardware-profile.json")
        archive.write(ROOT / "docs/XIAO_OPERATION.ko.md", "XIAO_OPERATION.ko.md")
        archive.write(ROOT / "contracts/protocol.md", "protocol.md")
        archive.write(ROOT / "scripts/firmware_upload.py", "upload.py")
        archive.writestr("hardware_profile.h", header)
        archive.writestr("flash_args", "\n".join(flash_args) + "\n")
        archive.writestr("README.ko.md", readme)
        archive.writestr("BUILD_REPORT.json", json.dumps(report, indent=2))
    output.with_suffix(".zip.sha256").write_text(sha(output) + "  " + output.name + "\n", encoding="ascii")
    print(json.dumps({"archive": str(output), "bytes": output.stat().st_size, "sha256": sha(output)}, indent=2))


if __name__ == "__main__":
    main()
