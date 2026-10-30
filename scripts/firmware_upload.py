"""Portable uploader for the prebuilt ZIP. Flash only with an explicit --port."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys

EXPECTED_FILES = {"0x0": "bootloader/bootloader.bin",
                  "0x8000": "partition_table/partition-table.bin", "0x10000": "sound_haptic.bin"}


def validate_package(folder):
    folder = Path(folder)
    config = json.loads((folder / "flasher_args.json").read_text(encoding="utf-8"))
    report = json.loads((folder / "BUILD_REPORT.json").read_text(encoding="utf-8"))
    if config.get("extra_esptool_args", {}).get("chip") != "esp32s3" or config.get("flash_files") != EXPECTED_FILES:
        raise ValueError("Wrong chip or flash layout; extract the original ZIP again.")
    expected_args = ["--flash_mode", "dio", "--flash_size", "4MB", "--flash_freq", "80m"]
    if config.get("write_flash_args") != expected_args:
        raise ValueError("Unexpected flash settings; extract the original ZIP again.")
    for name in EXPECTED_FILES.values():
        digest = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if digest != report.get("flash_sha256", {}).get(name):
            raise ValueError(f"Missing or changed firmware file: {name}; extract the original ZIP again.")
    return config


def build_command(folder, port):
    # Structured subprocess arguments, never a shell command or implicit port selection.
    if not re.fullmatch(r"COM[1-9][0-9]*|/dev/[A-Za-z0-9_./-]+", port, re.IGNORECASE):
        raise ValueError("Specify the board's actual port, for example COM5.")
    config = validate_package(folder)
    command = [sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", port,
               "write_flash", *config["write_flash_args"]]
    for offset, name in sorted(EXPECTED_FILES.items(), key=lambda item: int(item[0], 16)):
        command.extend((offset, name))
    return command


def main(argv=None, folder=None):
    parser = argparse.ArgumentParser(description="Upload the packaged ESP32-S3 firmware using Python + esptool 4.12.0")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--port", help="the explicitly selected board port, for example COM5")
    mode.add_argument("--check", action="store_true", help="verify packaged files without opening a serial port")
    mode.add_argument("--list-ports", action="store_true", help="list serial ports without writing to a board")
    parser.add_argument("--dry-run", action="store_true", help="print the upload arguments without running them")
    args = parser.parse_args(argv)
    folder = Path(folder) if folder else Path(__file__).resolve().parent
    if args.dry_run and not args.port:
        parser.error("--dry-run requires --port")
    try:
        if args.check:
            validate_package(folder)
            print("Firmware files verified. No board was connected or written.")
            return 0
        if args.port:
            command = build_command(folder, args.port)
            if args.dry_run:
                print(json.dumps({"cwd": str(folder), "command": command}, ensure_ascii=True))
                return 0
        try:
            version = importlib.metadata.version("esptool")
        except importlib.metadata.PackageNotFoundError:
            version = None
        if version != "4.12.0":
            raise ValueError('Install the uploader first: python -m pip install "esptool==4.12.0"')
        if args.list_ports:
            return subprocess.run([sys.executable, "-m", "serial.tools.list_ports", "-v"], check=False).returncode
        print(f"Uploading to {args.port}. Keep the data USB cable connected.", flush=True)
        result = subprocess.run(command, cwd=folder, check=False)
        if result.returncode == 0:
            print("Upload completed. Hold your external power button for 6 seconds to enter pairing mode.")
        return result.returncode
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
