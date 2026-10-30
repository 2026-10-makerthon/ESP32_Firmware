# 개발 환경과 빌드

2026-10-31 XIAO 변경: 현재 버튼·본딩·마이크·DRV2605L 사용 절차는 [XIAO 사용법](XIAO_OPERATION.ko.md)을 따른다. `-PhysicalHaptic`은 DM161을 ERM으로 가정한3V 목표 초기 구동 프로파일 `hardware/profiles/xiao-dm161-3v-prototype.json`을 선택한다. 실물 검증은 미완료이며 해당 표시를 켜지 않는다. 옵션을 빼면 기존 `xiao-inmp441-drv2605l.json`으로 로그 전용 진동을 사용한다.

## PC 개발

Windows용 Python3.12+, Git을 사용합니다. VS Code는 편집기로 선택할 수 있으며 실행에 필수는 아닙니다. `scripts/setup.ps1`은 프로젝트 안의 `.venv`만 준비하고 시스템 Python/기존 프로젝트를 변경하지 않습니다. Python·패키지 버전은 `versions.lock`, `requirements.lock.txt`에 기록합니다.

```powershell
.\scripts\setup.ps1 -Python 'C:\path\to\python.exe'
.\.venv\Scripts\python.exe -m harness demo
.\.venv\Scripts\python.exe -m harness verify --gate all
```

`verify --gate contract`는 파서/오디오/재조립, `faults`는 Python 상태·감지·클라이언트, `builds`는 PC에서 실제 C 소스 빌드 및 Python과 비교합니다. `builds`는 ESP-IDF 빌드라는 뜻이 아닙니다. 보드 빌드는 별도 스크립트를 사용합니다. 테스트의 expected는 매번 생성하지 않고 고정 `golden_vectors.json`을 읽습니다.

독립 벡터 생성기는 `scripts/make-vectors.py`입니다. Python3.12의 audioop 구현을 별도 oracle로 사용하며, 변경 후에는 검토가 필요합니다. 일반 설치·테스트·패키징에서는 이 스크립트를 실행하지 않습니다.

## 이 PC에 설치한 ESP32 도구

ESP-IDF v5.5.1을 프로젝트와 분리된 도구 폴더에 설치했습니다. 이 PC의 경로는 `versions.lock`에 있고, SDK 전용 Python 패키지는 `requirements.idf.lock.txt`에 기록했습니다. SDK/도구 폴더는 쓰기 허용된 Codex 작업 폴더 아래에 있고, 짧은 `S:` 경로는 그 폴더를 가리키는 `subst` 매핑입니다. 시스템 설정/전역 PATH를 영구 변경하지 않았습니다. `S:`가 다른 용도로 사용 중이면 임의로 덮어쓰지 마세요.

Windows 툴체인의260자 경로 제한과 프로젝트 폴더의 공백/한글을 피하기 위해, 빌드 스크립트는 펌웨어 소스를 짧은 ASCII 경로에 복사해 빌드합니다. 이 PC의 빌드 작업 폴더는 `C:\Users\junni\shdev\firmware-work`입니다. 원본 소스는 이 프로젝트의 `firmware/`이며 수정은 원본에서 합니다. 빌드 단계에서 보드를 검색하거나 플래시하지 않습니다.

```powershell
.\scripts\build-firmware.ps1 `
  -IdfPath 'S:\.tools\esp-idf' `
  -ToolsPath 'S:\.tools\idf-tools' `
  -BuildRoot 'C:\Users\junni\shdev\firmware-work'
```

현재 `S:`가 없는 경우 `versions.lock`에 기록된 `subst_target`이 실제 SDK 폴더인지 확인한 후, 비어 있는 드라이브 문자를 선택해 매핑합니다. `subst S: 경로`는 현재 Windows 로그인 세션의 경로 단축이며 재부팅 후 복원이 필요할 수 있습니다. 매핑 없이 SDK 실제 경로를 직접 지정할 수도 있지만 컴파일러의 깊은 내부 경로 제한에 주의하세요. 다른 PC에서는 공식 ESP-IDF 설치 관리자를 이용해 `C:\Espressif`처럼 짧은 위치에 v5.5.1을 설치하는 방법도 있습니다.

산출물은 `build/firmware-synthetic-mock/`에 `.bin/.elf`, bootloader, partition table, flasher_args.json으로 복사됩니다. bootloader/partition_table 하위 폴더 구조도 보존합니다. flasher_args.json의 상대 경로는 이 산출물 폴더를 기준으로 읽을 수 있습니다. 실제 플래시는 연결된 보드와 COM 포트를 명확히 확인한 뒤 별도 수행합니다.

## 실제 마이크 어댑터

```powershell
.\scripts\build-firmware.ps1 -IdfPath 'S:\.tools\esp-idf' `
  -ToolsPath 'S:\.tools\idf-tools' -BuildRoot 'C:\Users\junni\shdev\firmware-work' `
  -RealMicrophone
```

현재 어댑터는 INMP441의 standard Philips I2S,32bit stereo slots에서 왼쪽24bit를 추출합니다. 사용자 배선표의 핀은 BCLK2(D1),WS1(D0),DIN4(D3)이며 선택한 JSON 프로파일을 빌드 설정에 반영합니다. 실제 장치의 슬롯 정렬/부호/음량/클리핑을 캡처로 확인해야 합니다. 마이크가 바뀌면 `adapters.c`의 `sh_capture_read`를 교체합니다. profile2는 I2S 샘플 클록을8kHz로 재설정하며, 단순히16kHz 샘플을 건너뛰지 않습니다.

## 실제 진동 출력

DRV2605L I2C 어댑터는 SDA5/SCL6,주소0x5A, RTP로 기존 패턴의 강도를 적용합니다. 초기3V ERM 출력은 `-RealMicrophone -PhysicalHaptic`으로 빌드합니다. 프로파일 생성기가 목표3V 이하,전원3.3V 이하,ERM 개방루프를 검사하고 clamp와 제어 레지스터를 계산합니다. 출력 허용과 실물 검증 완료를 별도 상태로 관리합니다. 이전 PWM 모듈용 프로파일과 확인된 모터 정격·피크전류·보정·검증 기록을 요구하는 일반 검증 완료 경로도 유지합니다.

검증된 PWM 입력 모듈이라면 별도의 JSON 프로파일에서 `backend=pwm_module`, `enabled=true`, `input_3v3_verified=true`, 전원·전류·주파수,10bit weak/strong duty, `verification_record`를 기록합니다. 예제의 null을 임의 숫자로 대체하지 마세요. `hardware-header.py`가 조건을 검사해 C 헤더를 생성합니다.

```powershell
# 실제 검증된 프로파일이 있을 때만 사용
.\scripts\build-firmware.ps1 -IdfPath 'S:\.tools\esp-idf' `
  -ToolsPath 'S:\.tools\idf-tools' -BuildRoot 'C:\Users\junni\shdev\firmware-work' `
  -PhysicalHaptic -Profile 'C:\path\to\verified-profile.json'
```

물리 출력 어댑터는 DRV2605L의 signed RTP와 이전 PWM 모듈용 LEDC low-speed/10bit 구현을 지원합니다. ERM/LRA 단품을 GPIO에 직접 연결하지 않습니다. 논리 강도와 RTP/PWM의 선형 매핑이 체감 강도의 선형성을 보장하지는 않습니다.

## 실제 BLE와 보고서

`harness scan`은 matching service만 검색합니다. `harness hil --device ADDRESS --duration 1800 --play 2`는 명시된 장치에만 연결해 실제 데이터를 WAV/JSONL로 저장합니다. 자동 재연결/임의 장치 플래시는 하지 않습니다. 초기 진동 패턴 한 번을 실행하고 heartbeat를 계속 유지하며, 종료 시 STOP을 보냅니다. 지속적인 반복 패턴/정지/장애 주입은 HIL 체크리스트에 따라 별도 수행합니다.

PC BLE WAV는 수신한 burst를 이어 붙인 파일이며 원래 시각/gap은 sidecar JSONL에 있습니다. 오프라인 데모 WAV는3초 원래 시간축에 무전송 구간을0으로 채웁니다. 두 파일의 시간축 의미를 구분하세요.

## 공유 패키지 재생성

```powershell
.\.venv\Scripts\python.exe scripts/package.py
```

패키지는 명시된 소스/문서/고정 벡터/오프라인 예제/검증 요약만 포함합니다. `.venv`, `.tools`, `.git`, 실장비 캡처와 SDK 바이너리는 제외합니다. 상대 개발자는 압축을 풀고 setup부터 재현할 수 있습니다. SDK 라이선스는 SDK 원본을 따르며 이 ZIP에 재배포하지 않습니다.
