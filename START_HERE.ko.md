# 새 PC에서 소스 저장소 시작하기

Windows용 Git과 Python3.12+를 설치하고 저장소를 복제한다.

```powershell
git clone https://github.com/2026-10-makerthon/ESP32_Firmware.git
cd ESP32_Firmware
.\scripts\setup.ps1 -Python (py -3.12 -c "import sys; print(sys.executable)")
.\.venv\Scripts\python.exe -X utf8 -m harness verify --gate all
.\.venv\Scripts\python.exe -X utf8 -m harness demo
```

`py`가 없으면 설치한 Python 실행 파일의 실제 경로를 `-Python`에 지정한다. PowerShell이 스크립트를 차단하면 해당 실행에만 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Python 'C:\path\to\python.exe'`를 사용한다.

Codex에서 이어갈 때는 `AGENTS.md`, `CONTEXT_HANDOFF.ko.md`를 읽고 현재 사용법은 `docs/XIAO_OPERATION.ko.md`, 통신 규격은 `contracts/protocol.md`를 따른다. 인수인계 문서의 과거 PC 경로나 검증 결과를 현재 환경의 설치·실물 시험 결과로 간주하지 않는다.

## 펌웨어 빌드

ESP-IDF v5.5.1과 해당 도구를 별도로 설치한다. SDK의 실제 경로와 공백·한글이 없는 짧은 빌드 경로를 지정한다. 다음 경로는 예시다.

```powershell
.\scripts\build-firmware.ps1 -IdfPath 'C:\Espressif\esp-idf-v5.5.1' `
  -ToolsPath 'C:\Espressif\tools' -BuildRoot 'C:\sh-build' `
  -RealMicrophone -PhysicalHaptic
```

`-PhysicalHaptic`은 `hardware/profiles/xiao-dm161-3v-prototype.json`을 선택한다. DM161을 DC ERM으로 가정한 3V 목표 초기 출력이며 `VERIFIED=0`이다. 옵션을 빼면 로그 전용 진동 빌드다. 빌드는 보드에 업로드하지 않는다.

결과는 `build/firmware-mic-physical/`에 생성된다. 업로드는 실제 XIAO 보드와 포트를 확인한 뒤 ESP-IDF 도구를 사용하거나, 빌드 후 다음 명령으로 별도 패키지를 생성해 그 안의 `upload.py`를 사용한다.

```powershell
# 빌드 로그는 .tools/firmware-dm161-3v-build.log에 저장해야 한다.
.\.venv\Scripts\python.exe scripts/package-dm161-firmware.py --stage '실제 스테이징 펌웨어 폴더'
```

패키징에는 성공한 실제 출력 빌드와 최신 전체 테스트 보고서가 필요하다. 자세한 버튼·본딩·업로드 절차는 `docs/XIAO_OPERATION.ko.md`를 따른다.

## Git에 포함하지 않는 파일

`.venv/`, SDK·캐시, `build/`, `dist/`, `ready-to-flash/`, `harness/reports/`, `evidence/`, `examples/` 및 인수인계 ZIP의 manifest는 로컬 산출물이다. `harness demo`의 합성 오디오와 패킷은 `build/demo/`에 새로 생성한다. 개인 오디오와 비밀값을 커밋하지 않는다.
