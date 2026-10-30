# 소리 전달 · 진동 제어 개발 키트

XIAO ESP32-S3 펌웨어와 BLE 통신 계약, PC 검증 도구를 관리하는 소스 저장소입니다. [새 PC 시작 안내](START_HERE.ko.md)와 [현재 맥락 요약](CONTEXT_HANDOFF.ko.md)을 먼저 읽으세요.

빌드 바이너리, 녹음, 자동 생성 보고서와 로그, 인수인계 ZIP 메타데이터는 Git에서 제외합니다. 문서에 나오는 `ready-to-flash/`, `examples/`, `harness/reports/`, `dist/`는 로컬 생성물 또는 별도 배포 패키지이며 클론에 포함되지 않습니다. 과거 검증 기록은 [현재 상태](docs/STATUS.ko.md)에 보존합니다. 실물 검증은 아직 완료하지 않았습니다.

2026-10-31: XIAO ESP32-S3 배선표의 **3초 전원·6초 페어링, 본딩 재연결, INMP441 소리 압축 전송, DRV2605L 진동 명령**에 더해 DM161의 **3V 목표 초기 출력 모드**를 추가했습니다. `-RealMicrophone -PhysicalHaptic`으로 실제 출력용 빌드를 선택합니다. 모터를 ERM으로 가정한 초기 설정이며 실물 검증·보정 완료 표시는 켜지 않습니다. [버튼·연결·빌드 사용법](docs/XIAO_OPERATION.ko.md)을 참고하세요.

모듈이 정해지기 전에 병행 개발할 수 있는 **BLE 통신 규격, Python 참조 구현, 실제 펌웨어와 공용으로 사용하는 C 코어, ESP32-S3 펌웨어, PC BLE 테스트 클라이언트**입니다. 휴대폰 앱 구현은 포함하지 않습니다.

처음 보는 개발자는 [개발자 연동 안내](docs/DEVELOPER_HANDOFF.ko.md)부터 읽으세요. **유일한 통신 규격은 [contracts/protocol.md](contracts/protocol.md)**입니다. 이전 설계 문서의 미확정 값은 이 규격으로 보완했습니다.

## 바로 실행

Windows Python3.12+를 설치한 뒤 PowerShell에서 프로젝트 폴더를 열고 환경을 준비합니다. 가상환경과 ESP-IDF는 저장소에 포함하지 않습니다.

```powershell
.\scripts\setup.ps1 -Python 'C:\path\to\python.exe'
```

```powershell
.\.venv\Scripts\python.exe -m harness demo
.\.venv\Scripts\python.exe -m harness verify --gate all
```

첫 명령은 보드 없이 가짜 장치와 실제 형식의 패킷을 주고받고 `build/demo/received.wav`, `packets.jsonl`, `summary.json`을 만듭니다. 두 번째 명령은 Python·C 교차 검증과 오류/시간/연결 시험을 실행합니다. 결과는 `harness/reports/`에 기록합니다. 샌드박스 안에서는 네이티브 컴파일러/Windows 비동기 타이머 실행에 추가 실행 권한이 필요할 수 있습니다.

배포된 고정 벡터를 사용하는 테스트에는 audioop가 필요하지 않습니다. 벡터를 새로 감사·생성하는 유지보수 스크립트만 Python3.12가 필요합니다. Windows 의존성은 `requirements.lock.txt`, 주요 버전과 SDK 식별자는 `versions.lock`에 기록합니다.

## 실제 BLE 장치가 있을 때

```powershell
.\.venv\Scripts\python.exe -m harness scan --seconds 5
.\.venv\Scripts\python.exe -m harness hil --device '실제 검색된 주소' --duration 10
# 진동 명령도 함께 시험하려면 --play 2 추가
```

실제 장치 식별자가 없으면 연결하거나 플래시하지 않습니다. PC 도구는 자동 재연결하지 않으며, 실패 시 다시 실행해 새 세션으로 시작합니다. Android 연동 성공을 대신 보장하지 않습니다.

## 구성

| 경로 | 내용 |
|---|---|
| `contracts/` | 고정 통신 규격, 패턴, 독립 구현 기반 검증 벡터 |
| `harness/` | Python SDK/가짜 장치/오디오 복원/PC BLE 클라이언트 |
| `firmware/components/sh_core/` | 하드웨어 의존성이 없는 C 파서·코덱·감지·명령·진동·오디오 큐 |
| `firmware/main/` | NimBLE GATT, I2S, PWM/가짜 장치 어댑터 |
| `hardware/profiles/` | 모듈별 핀·전원·검증 상태 |
| `tests/` | 계약·오류·C/Python 일치 검증 |
| `docs/` | 설치·연동·실장비 체크리스트·현재 상태 |
| `scripts/` | 재현 가능한 환경 준비·빌드·공유 ZIP 생성 |

펌웨어 빌드는 [개발 환경 안내](docs/DEVELOPMENT.ko.md), 검증 범위와 남은 실물 시험은 [현재 상태](docs/STATUS.ko.md)를 참고하세요. 기본 펌웨어는 **합성 소리 + 로그 전용 진동**입니다. 부품을 정하면 어댑터와 hardware profile을 변경하고 같은 규격으로 통합합니다.
