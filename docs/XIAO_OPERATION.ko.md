# XIAO 버튼·페어링·소리 전송 사용법

2026-10-31. 대상은 사용자 배선표의 XIAO ESP32-S3 + INMP441 + DRV2605L이다. DM161의3V 목표 초기 출력용 프로파일과 실제 출력 빌드를 추가했다. 실제 보드 플래시·무선·모터 동작은 아직 시험하지 않았다.

모터는 사용자가 **DM161, 80mA, 3V와3.7V가 모두 표기됨**으로 알려주었다. 두 전압을 기록하고 정격전압은 미확정으로 남겼다. 이 두 숫자를 확인된 허용 동작 범위로 간주하지 않는다. 사용자가3V 목표로 진행을 요청하여 DC 모터를 ERM으로 가정한 개방루프 초기 구동 프로파일을 만들었다.80mA는 사용자 제공 정보이며 기동/구속 피크나 소프트웨어 전류 제한값으로 사용하지 않는다. 실제 모터 종류·출력·기동·진동 세기·전류는 실물 확인 대상이다.

현재 배선의 드라이버 공급전압은3.3V다.3V 목표 개방루프 출력은 [TI SLOS854D 식6](https://www.ti.com/lit/ds/symlink/drv2605l.pdf)에 따라 OD_CLAMP=`floor(3.0/0.02159)`=138(0x8A)로 내려 계산했으며 명목 평균 구동값은 약2.97942V다. 이는 측정값이나 모든 순간의 전압이3V 이하라는 보장이 아니다. 모터 단자는 스위칭 출력이다. 공급전압 보상은 유지하고 startup boost는 끈다. 자동 보정과 ROM 효과 재생은 사용하지 않고 기존5ms 패턴을 signed RTP0..127로 적용한다. 전원 배선은 바꾸지 않는다.

초기 출력용 프로파일 `hardware/profiles/xiao-dm161-3v-prototype.json`은 실제 출력을 허용하지만 실물 검증 완료로 표시하지 않는다. Capabilities feature bit0과 GET_STATE의 HARDWARE_VERIFIED는0을 유지한다. 이 빌드에서는 해당 표시가0이어도 PLAY_PATTERN이 물리 출력을 만들 수 있다. 권한은 빌드 프로파일로만 선택하며 BLE 명령으로 활성화할 수 없다. 기존 미확정 프로파일과 로그 전용 빌드는 실제 출력 비활성 상태를 유지한다.

## 버튼

| 현재 상태 | 조작 | 결과 |
|---|---|---|
| 꺼짐 | 3초 미만 누른 뒤 놓기 | 꺼짐 유지 |
| 꺼짐 | 3초 이상, 6초 미만 누른 뒤 놓기 | 일반 부팅, 저장된 기기 연결 대기 |
| 꺼짐 | 6초 이상 계속 누르기 | 페어링 부팅, 새 기기 등록을 최대 120초 허용 |
| 켜짐 | 3초 이상 계속 누르기 | 음성·진동·BLE 종료, 버튼을 놓으면 딥슬립 |
| 켜짐 | 짧게 누르기 | 동작 없음 |

일반 부팅은 버튼을 놓을 때 결정한다. 3초에 즉시 켜지면 같은 누름의 6초 페어링 동작과 전원 끄기가 충돌하기 때문이다. 6초 페어링으로 부팅한 누름은 놓기 전까지 전원 끄기로 다시 해석하지 않는다. 접점 튐은 30ms로 걸러낸다. 켜기 시간은 딥슬립 복귀 후 펌웨어가 버튼을 읽기 시작한 시점부터 계산하므로 물리적으로 누른 시간에 부팅 지연이 조금 더해진다.

배터리나 USB를 처음 연결했을 때 버튼이 눌려 있지 않으면 꺼진 상태로 시작한다. 버튼은 GPIO7–GND이고 내부 풀업을 사용한다. GPIO7의 RTC EXT0 LOW 레벨로 깨운다. 끄는 동안 계속 누르고 있으면 즉시 재기동하지 않도록 버튼 해제를 기다린다.

**현재 배선의 꺼짐은 소프트웨어 딥슬립이다.** 배터리 전원선을 물리적으로 차단하지 않는다. 3V3에 연결된 마이크·드라이버와 보드 전원회로에는 전원이 남고, DRV2605L에는 대기 모드를 요청한다. 완전한 전원 차단은 별도 전원 래치/로드 스위치 회로가 필요하다. 대기전류는 미측정이다.

## 핀

| 기능 | 보드 표기 | 코드 GPIO |
|---|---|---|
| INMP441 WS | D0 | 1 |
| INMP441 SCK | D1 | 2 |
| INMP441 SD | D3 | 4 |
| DRV2605L SDA | D4 | 5 |
| DRV2605L SCL | D5 | 6 |
| 버튼, 다른 쪽은 GND | D8 | 7 |

INMP441 L/R은 GND, 왼쪽 슬롯이다. 양쪽 32bit Philips 슬롯을 수신하여 왼쪽 24bit를 추출한다. 모터는 DRV2605L OUT+/OUT−에만 연결한다. DRV2605L 모듈의 EN이 HIGH로 유지되고 I2C 풀업이 3.3V로 연결되는 모듈을 사용해야 한다. 일반 코인형이라는 외형만으로 ERM/LRA와 정격전압을 확정하지 않는다.

## 페어링과 재연결

1. 꺼진 상태에서 6초 이상 누른다. `SoundHaptic-pair`로 광고한다.
2. BLE 클라이언트에서 서비스 UUID를 검색하고 연결·페어링한다. Secure Connections Just Works로 암호화하고 한 기기의 키를 NVS에 보관한다. 화면/키패드가 없으므로 숫자 대조나 MITM 인증은 제공하지 않는다.
3. 암호화·본딩 완료 후에만 Capabilities, Control, Event, Audio를 사용한다. 페어링 성공 시 등록 창은 닫힌다. 연결 후 보안 절차가 10초 내에 끝나지 않으면 연결을 끊는다.
4. 다음 일반 부팅은 저장된 기기만 허용한다. 보드는 주변장치로 광고하며, 휴대폰/PC 클라이언트가 연결을 시작한다. 앱의 자동 재연결 구현이 필요하다.

6초 페어링 부팅은 **기존 등록 키를 지우고 새 등록을 시작**한다. 상대 휴대폰/PC에도 이전 키가 남아 있다면 해당 기기를 삭제/등록 해제한 뒤 다시 페어링한다. 120초 내 등록하지 못하면 등록 창이 닫히며, 껐다가 다시 6초로 진입한다. 등록된 기기가 없는 일반 부팅에서는 새 기기 등록을 허용하지 않는다. 일반 부팅 중 상대가 키 재발급을 요청해도 거절한다.

UUID·opcode·패킷·압축 형식은 기존 [BLE 계약](../contracts/protocol.md)을 유지한다. GATT 연결 앞에 표준 BLE 페어링/암호화 단계가 추가되었다. 구형의 비암호화 전용 클라이언트는 보안 연결 지원이 필요하다. 일반 Bluetooth 헤드셋/오디오 프로파일이 아니므로 이 BLE 인터페이스를 구현한 클라이언트가 필요하다.

## 켜진 동안 동작

마이크를 계속 수집한다. 클라이언트가 연결할 때 Event 구독 → GET_STATE → Audio 구독 → SET_DETECTION → START_AUDIO(profile 1)를 자동 수행하면, 이후 큰 소리마다 추가 명령 없이 전송한다. 기본 감지는 -45dBFS에서 시작, -50dBFS 아래에서 500ms 지속되면 종료하며, 최대 100ms의 직전 소리를 포함한다. dBFS는 마이크 신호 크기이며 실제 음압 dB SPL로 보정한 값은 아니다.

음성은 16kHz mono, 20ms당 320개 샘플을 독립 IMA ADPCM 블록 164바이트로 압축한다. 전송 헤더는 16바이트다. 큰 소리가 계속되면 계속 전송하고 조용해지면 멈춘다. 연결이 없으면 저장/나중 재전송하지 않는다. 연결이 끊기면 새 세션에서 다시 구독·설정·arm한다.

진동은 수신한 PLAY_PATTERN의 패턴·강도·반복·TTL에 따라서만 동작한다. 5ms 스케줄러의 논리 강도를 DRV2605L의 I2C Real-Time Playback 값으로 매핑한다. ROM 효과 번호로 기존 패턴을 대체하지 않는다. 소리 자체가 모터를 켜지는 않는다. 진동 중에도 소리 감지·압축·전송을 계속하며 MOTOR_ACTIVE를 표시한다.

STOP_HAPTIC, 연결 해제, 1500ms heartbeat 만료, TTL 만료, 전원 종료에서 정지한다. 클라이언트는 기존 계약대로 500ms마다 HEARTBEAT를 보내야 한다. I2C 오류가 나면 RTP=0과 standby를 시도하고 출력을 비활성화한다. EN을 별도 GPIO로 연결하지 않은 현재 표에서는 버스 단선·MCU 정지 시 드라이버 전원을 하드웨어로 차단할 수 없다. 이 장애에서의 실제 정지는 실물 시험 대상이다.

## 빌드와 PC 확인

### 다른 Windows PC에 업로드

`dist/dm161-3v-prototype-esp32s3.zip` 전체를 옮겨 압축을 푼다. Python3.12와 인터넷 연결을 준비하고 압축을 푼 폴더의 주소 표시줄에 `powershell`을 입력해 연다. 빌드된 파일을 쓰는 데 ESP-IDF나 Arduino IDE는 필요하지 않다.

```powershell
py -3 -m pip install "esptool==4.12.0"
py -3 upload.py --list-ports
py -3 upload.py --port COM5
```

COM5는 예시다. 데이터 USB로 XIAO를 연결하고, 보드의 BOOT을 누른 채 RESET을 한 번 누른 후 BOOT을 놓아 업로드 모드로 진입한다. 장치 관리자나 `--list-ports`로 확인한 실제 보드 포트를 지정한다. `py`가 없으면 PATH에 등록된 `python`으로 `py -3`을 대체한다. 도구 설치는 최초 한 번만 필요하다. `--check`는 파일만 검사하고 `--port`를 지정한 명령만 실제 업로드한다. 업로드 완료 후 추가한 전원 버튼을6초 유지하면 페어링 모드다.

업로드 도구와 설치 방법은 [Espressif esptool 문서](https://docs.espressif.com/projects/esptool/en/release-v4/esp32s3/installation.html), BOOT 조작은 [Seeed 안내](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/#bootloader-mode)를 따른다.

### 소스에서 다시 빌드

```powershell
.\scripts\build-firmware.ps1 -IdfPath 'S:\.tools\esp-idf' `
  -ToolsPath 'S:\.tools\idf-tools' -BuildRoot 'C:\Users\junni\shdev\firmware-work' `
  -RealMicrophone -PhysicalHaptic
```

`-PhysicalHaptic`은 기본으로 `hardware/profiles/xiao-dm161-3v-prototype.json`을 선택하며 산출물은 `build/firmware-mic-physical/`이다. 마이크 핀과 버튼 핀도 프로파일을 따른다. 실제 출력 없이 확인하려면 `-PhysicalHaptic`을 빼며, 이 경우 기존 미확정 프로파일과 `build/firmware-mic-mock/` 산출물을 사용한다. 빌드만으로 보드에 플래시하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m harness scan --seconds 5
# 최초 등록은 보드의 6초 페어링 부팅 후 실행
.\.venv\Scripts\python.exe -m harness hil --device '검색된 실제 주소' --pair --duration 10
# 기존 등록 기기에서 일반 부팅 후 실행
.\.venv\Scripts\python.exe -m harness hil --device '검색된 실제 주소' --duration 10
```

초기 구동 프로파일은 `prototype=true`, `enabled=true`, ERM 개방루프, 전원3.3V 이하·목표3V 이하로 제한된다. 전압 레지스터는 생성기가 계산하고 수동 덮어쓰기는 거절한다. SH_HW_OUTPUT_ENABLED=1과 SH_HW_VERIFIED=0을 분리하며, 검증 기록을 가짜로 채우지 않는다. 실제 전원·기동전류·출력·정지 동작과 촉각을 확인한 후 검증 완료 프로파일을 따로 만든다. 검증 완료 경로의 모터 정격·피크전류·보정 레지스터·verification_record 요구는 유지한다. I2C 초기화가 실패하면 진동만 비활성화하고 버튼·음성 기능은 유지한다.

소스는 `firmware/main/power.c`, `main.c`, `drv2605.c`, `adapters.c`와 `firmware/components/sh_core/`다. 보드 플래시는 이 문서의 명령에 포함되지 않는다.

## 참고한 제조사 자료

- [Seeed XIAO ESP32-S3 핀 배치](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
- [Espressif ESP-IDF v5.5.1 딥슬립/EXT0](https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32s3/api-reference/system/sleep_modes.html)
- [Espressif v5.5.1 NimBLE 본딩 예제](https://github.com/espressif/esp-idf/blob/v5.5.1/examples/bluetooth/nimble/bleprph/main/main.c)
- [TI DRV2605L 데이터시트](https://www.ti.com/lit/ds/symlink/drv2605l.pdf)
