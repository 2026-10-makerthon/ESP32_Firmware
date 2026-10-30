# 다른 PC의 Codex가 이어받을 맥락

기준일:2026-10-31,한국시간. 이 문서는 지금까지의 요구·결정·구현·검증·남은 일을 요약한 인수인계다. 대화 원문이나 Codex 계정/채팅 상태를 내보낸 파일은 아니다. 소스 스냅샷과 이 요약을 새 채팅에서 읽고 이어간다.

## 사용자가 원하는 장치

XIAO ESP32-S3가 소리를 계속 감시하다가 일정 크기 이상이면 기존 BLE 인터페이스로 압축 음성을 보내고, 외부에서 진동 명령을 받으면 패턴과 강도에 맞게 모터를 실행한다. 소리 자체로 모터를 켜는 기능이 아니다. 사용자는 배선표 설명 대신 실제 코드를 원했으며, 현재는 **다른 PC에 보드를 연결하여 업로드하고 이어서 확인할 예정**이다.

전원/페어링 요구와 현재 구현:

| 상태 | 조작 | 결과 |
|---|---|---|
| OFF |3초 미만 누르고 놓기 |OFF 유지 |
| OFF |3초 이상6초 미만 누르고 놓기 |일반 부팅,저장 기기 연결 대기 |
| OFF |6초 이상 계속 누르기 |페어링 부팅 |
| ON |3초 이상 누르기 |음성·진동·BLE 종료,버튼 해제 후 딥슬립 |

일반 부팅은 버튼을 놓을 때 결정하여6초 페어링과 충돌하지 않게 했다. 켜기 시간에는 딥슬립 복귀/부팅 지연이 조금 더해진다. 페어링 부팅에 사용한 누름은 해제 전까지 끄기로 다시 해석하지 않는다. 접점 튐30ms. 배터리/USB 연결 때 버튼이 눌리지 않았으면 OFF로 시작한다. **OFF는 딥슬립이며 배터리 전원 차단이 아니다.**

## 현재 배선

| 부품 핀 | XIAO 표기 | 코드 GPIO/연결 |
|---|---|---|
| INMP441 VDD |3V3 |브레드보드+ |
| INMP441 GND,L/R |GND |브레드보드−,왼쪽 슬롯 |
| INMP441 WS |D0 |GPIO1 |
| INMP441 SCK |D1 |GPIO2 |
| INMP441 SD |D3 |GPIO4 |
| DRV2605L VIN |3V3 |브레드보드+ |
| DRV2605L GND |GND |브레드보드− |
| DRV2605L SDA |D4 |GPIO5 |
| DRV2605L SCL |D5 |GPIO6 |
| 추가한 전원 버튼 |D8–GND |GPIO7,내부 풀업,LOW 누름 |
| 모터+/− |DRV2605L OUT+/OUT− |GPIO에 직접 연결하지 않음 |
| 1S LiPo+/− |XIAO 뒷면 BAT+/BAT− |사용자 배선 계획,실물 미확인 |

이 배선표가 현재 기준이다. `hardware/wiring.md` 아래쪽의 ESP32-S3 SuperMini/EM-MA-126/승압기/충전기 내용은 과거 후보 기록이며 현재 배선과 섞지 않는다. DRV 모듈의 EN이 HIGH로 유지되고 I2C 풀업이3.3V에 연결되는지는 실제 모듈에서 확인한다.

## DM161과3V 출력 결정

사용자는 모터 모델을 DM161로 알려준 뒤 DC3.7V·80mA라고 했고,3V라고도 쓰여 있다고 정정했다. 그래서 정격을 확정하거나3~3.7V 전체가 허용 범위라고 단정하지 않았다.80mA를 기동/구속 최대전류로 간주하지 않는다. 마지막에 사용자가3V 목표 실제 설정 진행을 승인했다.

현재 실제 출력용 프로파일은 `hardware/profiles/xiao-dm161-3v-prototype.json`이다.

- DC 모터를 **ERM으로 가정**한 초기 개방루프 출력이며 실물 종류 확인은 미완료다.
- DRV 전원은 기존3.3V를 유지한다. TI DRV2605L SLOS854D 식6: 평균값=0.02159×OD_CLAMP.3V 목표를 내림 계산하여 OD_CLAMP=138(0x8A),명목 평균 약2.97942V다.
- signed RTP0..127로 기존 논리 강도와 패턴을 적용한다. startup boost OFF,전원 보상 ON,자동 보정/ROM 효과는 사용하지 않는다.
- 이 값은 실제 측정값이나 모든 순간의 최대전압 보장이 아니다.80mA 소프트웨어 전류 제한을 구현한 것도 아니다.
- `SH_HW_OUTPUT_ENABLED=1`, `SH_HW_PROTOTYPE=1`, **`SH_HW_VERIFIED=0`**다. 출력 허용과 실물 검증을 구분한다.
- C 코어의 로컬 `prototype_output` 허용으로 PLAY를 수락한다. 이 허용을 BLE 명령으로 켤 수 없다. Capabilities feature bit0과 GET_STATE HARDWARE_VERIFIED는0을 유지한다. 실제 마이크+실제 출력 빌드의 feature bits는0x0e다.
- I2C 오류는 standby와RTP0을 시도하고 출력을 latch하여 자동 재진동하지 않는다. 초기화 실패 시 진동만 비활성화하고 버튼·음성은 유지한다. EN 제어선이 없는 현재 배선에서 버스 단선/MCU 정지의 실제 출력 차단은 아직 확인하지 못했다.

`hardware/profiles/xiao-inmp441-drv2605l.json`은 미확정 사양 기록과 로그 전용 경로다. 소스 트리의 기본 `firmware/main/hardware_profile.h`는 이 비활성 프로파일에서 생성되어 있으므로,그 파일의 OUTPUT_ENABLED=0을 보고 실제 출력용 패키지까지 비활성이라고 판단하지 않는다. 실제 출력 빌드 스크립트는 선택 프로파일로 스테이징 헤더를 다시 생성한다. 두 경로를 구분해 유지한다.

## BLE와 음성

- ESP-IDF v5.5.1、C/NimBLE、I2S. 기본 서비스 UUID=`8e1f0000-6f5a-4d7c-a321-9b7e2c1048d0`. 전체 계약은 `contracts/protocol.md`다.
-6초 페어링 부팅은 이전 본딩 키를 삭제하고120초 등록을 허용한다. 한 기기의 Secure Connections Just Works 본딩 키를NVS에 보존한다. 화면/키패드가 없어MITM 숫자 대조는 제공하지 않는다.
- 일반 부팅은 저장 기기만 허용한다. 보드는 주변장치로 광고하고 클라이언트가 연결을 시작한다. 키가 상대PC/폰에 남았으면 해당 기기의 등록을 해제한 뒤 새로 페어링한다.
- 암호화/본딩/16byte 키 확인 후 애플리케이션 데이터를 허용한다. 표준 헤드셋/시스템 Bluetooth 마이크가 아닌 전용 GATT 오디오 서비스다.
- 클라이언트가 연결 때 구독·GET_STATE·SET_DETECTION·START_AUDIO(profile1)를 자동 수행해야 한다. 이후 큰 소리마다 새 명령 없이 전송한다. 연결하지 않으면 녹음 저장이나 나중 재전송은 없다.
-16kHz mono、20ms/320samples、독립 IMA ADPCM164bytes+전송 헤더16bytes. 기본 -45dBFS 시작/-50dBFS 종료、500ms hold、최대100ms pre-roll. dB SPL로 보정한 값이 아니다.
-5ms 진동 패턴 스케줄러. HEARTBEAT500ms、lease1500ms、최대TTL5000ms. STOP/끊김/lease/TTL/전원 종료에서 정지한다. 진동 중에도 오디오 전송하며 MOTOR_ACTIVE로 표시한다.
- 외부 휴대폰 앱은 이 작업에서 만들지 않았다. 새 PC에서 업로드/보드 시험을 이어가는 것이 현재 단계다.

## 구현 위치

| 위치 | 역할 |
|---|---|
| firmware/main/main.c |GATT、본딩、오디오/전송/스케줄러 연결 |
| firmware/main/power.c |전원 버튼、RTC EXT0 딥슬립 |
| firmware/main/drv2605.c |DRV I2C/RTP/standby/오류 latch |
| firmware/main/adapters.c |INMP441、진동 어댑터、출력/검증 분리 |
| firmware/components/sh_core/ |공용C 프로토콜/ADPCM/감지/장치/버튼/본딩정책 |
| harness/ |Python 참조、가짜 장치、실제PC BLE 클라이언트 |
| scripts/hardware-header.py |프로파일 검사、3V 초기 레지스터 생성 |
| scripts/build-firmware.ps1 |SDK를 사용해 ASCII 경로에서 실제 빌드 |
| scripts/firmware_upload.py |패키지에서 upload.py로 제공되는 휴대용 업로더 |
| ready-to-flash/ |이번 인수인계에 들어 있는 이미 빌드된 실제 출력 파일 |

## 검증 근거와 현재 경계

인수인계 직전 최신 전체 PC/C 회귀는 **97개 통과,실패0**이다. 이전 실제 출력 빌드 당시에는93개,휴대용 업로더는4개를 별도로 시험했으며 이번에 전체97개를 함께 다시 실행했다. 이미 빌드한 파일의 BUILD_REPORT에93개라고 남아 있는 것은 당시 시험 기록이고 최신 소스 전체 보고서는 `harness/reports/all_report.json`이다. `dm161_3v_firmware_report.json`과 `docs/STATUS.ko.md`도 참고한다.

ESP32-S3 실제 마이크+실제 출력 빌드는 성공했다. 앱610,912bytes. SHA256은 포함된 BUILD_REPORT/manifest에 기록한다. 업로더 파일 해시 검사、COM 명시、잘못된 레이아웃 거절、압축 해제 후 --check/--dry-run을 확인했다. 이 검증은 보드를 쓰지 않는 PC/컴파일 시험이다.

**아직 하지 않은 것:** 보드 플래시,실물 버튼 복귀,실제 마이크 음질/슬롯/감지 보정,모터 전압·기동전류·촉각·정지,무선 본딩/키 복원/처리량/내구성,실제 휴대폰 연동. 현재 PC에서는 직렬 포트를 찾지 못했고 실제 COM/BLE 주소도 지정되지 않았다. 다른 PC에서 새로 식별해야 한다.

## 새 PC에서 이어갈 일

1. 인수인계 ZIP을 새 폴더에 풀고 `START_HERE.ko.md`를 읽는다. 이 폴더를 Codex 프로젝트로 연다.
2. 파일 검사는 `python scripts/verify-handoff.py` 또는Python launcher로 실행한다. 이 명령은 포트를 열지 않는다.
3. 현재 사용자가 업로드/장비 시험을 요청하면 USB/BOOT/RESET과 실제 COM 포트를 확인하고 `ready-to-flash/upload.py`로 진행한다. 임의 장치에 쓰지 않는다.
4. 업로드 후 외부 전원 버튼6초로 페어링하고 `harness ... hil --pair`로 기존 인터페이스를 시험한다. 초기에는 낮은 강도의 짧은 명령으로 모터 기동을 관찰하고,전압/전류/정지 동작은 측정해 기록한다. 관측 결과가 다르면 프로파일을 조정한다.
5. 실물 결과를 날짜·보드/모듈·포트·펌웨어 해시와 함께 기록하고 해당 변경에 필요한 테스트를 실행한다.

새 PC에 없는 것은 정상: `.venv`, ESP-IDF SDK, 컴파일러 캐시, Codex 로그인/채팅 DB,과거PC의S: 드라이브. `versions.lock`과 오래된 로그의 절대경로는 과거 환경 증거이며 새 PC 설치 경로가 아니다. 소스와 기본 예제/고정 벡터는 패키지에 포함한다. 개인 오디오·이전 하드웨어 사진·계정/비밀값·Git DB는 포함하지 않는다.
