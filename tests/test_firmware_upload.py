import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("firmware_upload", ROOT / "scripts/firmware_upload.py")
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)


@pytest.fixture
def package(tmp_path):
    folder = tmp_path / "다른 PC firmware"
    folder.mkdir()
    hashes = {}
    for name in upload.EXPECTED_FILES.values():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = ("software fixture " + name).encode()
        path.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    config = {"extra_esptool_args": {"chip": "esp32s3"}, "flash_files": upload.EXPECTED_FILES,
              "write_flash_args": ["--flash_mode", "dio", "--flash_size", "4MB", "--flash_freq", "80m"]}
    (folder / "flasher_args.json").write_text(json.dumps(config))
    (folder / "BUILD_REPORT.json").write_text(json.dumps({"flash_sha256": hashes}))
    return folder


def test_upload_uses_explicit_port_and_package_folder_with_structured_args(package, monkeypatch):
    calls = []
    monkeypatch.setattr(upload.importlib.metadata, "version", lambda _: "4.12.0")
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(upload.subprocess, "run", run)
    assert upload.main(["--port", "COM5"], folder=package) == 0
    assert len(calls) == 1
    command, options = calls[0]
    assert command[:8] == [upload.sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", "COM5", "write_flash"]
    assert command[-6:] == ["0x0", "bootloader/bootloader.bin", "0x8000", "partition_table/partition-table.bin", "0x10000", "sound_haptic.bin"]
    assert options == {"cwd": package, "check": False}


def test_check_and_dry_run_never_execute_or_open_serial(package, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("read-only mode invoked an external process")
    monkeypatch.setattr(upload.subprocess, "run", forbidden)
    assert upload.main(["--check"], folder=package) == 0
    assert upload.main(["--port", "COM5", "--dry-run"], folder=package) == 0
    with pytest.raises(SystemExit):
        upload.main([], folder=package)


def test_changed_binary_rejected_before_upload(package, monkeypatch):
    monkeypatch.setattr(upload.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected write"))
    (package / "sound_haptic.bin").write_bytes(b"changed")
    assert upload.main(["--port", "COM5"], folder=package) == 2


def test_wrong_chip_layout_and_invalid_port_are_rejected(package):
    with pytest.raises(ValueError):
        upload.build_command(package, "COM5 --erase-all")
    config = json.loads((package / "flasher_args.json").read_text())
    config["flash_files"]["0x0"] = "sound_haptic.bin"
    (package / "flasher_args.json").write_text(json.dumps(config))
    with pytest.raises(ValueError):
        upload.build_command(package, "COM5")
