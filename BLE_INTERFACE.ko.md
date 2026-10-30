# 외부 휴대폰 측 연동용 BLE 인터페이스

> 이 파일은 초기 설계 초안입니다. 구현된 v1.0의 최종 규격은 [contracts/protocol.md](contracts/protocol.md), 공유용 시작 안내는 [docs/DEVELOPER_HANDOFF.ko.md](docs/DEVELOPER_HANDOFF.ko.md), 검증 상태는 [docs/STATUS.ko.md](docs/STATUS.ko.md)를 사용하세요. heartbeat 전용 처리 경로 등 초안의 보완 사항도 최종 규격에 명시했습니다.

상태: 설계 초안. 실제 펌웨어가 구현·검증된 상태가 아니다. 상세 바이트 계약은 HARNESS_DESIGN.ko.md를 기준으로 하며 구현 시 contracts/protocol.md로 고정한다. Capabilities의 바이트 구조·오류 detail 숫자·state_flags 값은 계약 gate에서 확정할 항목이다.

## 역할과 범위

보드는 BLE peripheral/GATT server이고 휴대폰은 BLE central/GATT client다. 보드에서 임계값 이상의 소리를 감지하면 오디오를 Notify로 보내고, 휴대폰이 Control 특성에 명령을 쓰면 보드가 진동을 실행한다. 휴대폰 앱은 외부 담당이며 보드 프로젝트에서 구현하지 않는다.

이 API는 HTTP endpoint가 아니라 BLE UUID와 바이너리 패킷으로 구성된다. 휴대폰 측에는 서비스 검색·구독·명령 쓰기를 수행할 클라이언트가 필요하다.

## 서비스와 특성

Service UUID: `8e1f0000-6f5a-4d7c-a321-9b7e2c1048d0`

| 특성 | UUID | 사용 |
|---|---|---|
| Audio | `8e1f0001-6f5a-4d7c-a321-9b7e2c1048d0` | Notify 구독, 오디오 수신 |
| Control | `8e1f0002-6f5a-4d7c-a321-9b7e2c1048d0` | Write with response, 명령 전송 |
| Event | `8e1f0003-6f5a-4d7c-a321-9b7e2c1048d0` | Indicate 구독, 명령 결과 수신 |
| Capabilities | `8e1f0004-6f5a-4d7c-a321-9b7e2c1048d0` | Read, 지원 버전/형식/패턴 확인 |

## 연결 순서

1. 서비스 UUID로 검색하고 연결한다. 표시 이름에만 의존하지 않는다.
2. 서비스/특성을 탐색하고 Event Indicate를 활성화한다.
3. GET_STATE를 session_id=0으로 보내 Event 헤더에서 현재 session_id를 얻는다.
4. MTU를 협상한다. 기본 오디오는 실제 MTU 185 이상에서 허용되며 권장 요청값은 247 이상이다. 협상 결과를 확인한다.
5. Audio Notify를 활성화한다.
6. SET_DETECTION으로 크기 기준과 hold/pre-roll을 설정한다.
7. START_AUDIO(profile_id=1)를 보내 자동 감지 전송을 활성화한다.
8. 이후 보드는 큰 소리가 감지될 때마다 자동 전송한다. 매번 START_AUDIO를 다시 보내지 않는다.
9. 진동을 사용하는 동안 HEARTBEAT를 500ms마다 전송한다. 1500ms 동안 유효 heartbeat가 없으면 실행 중인 진동은 중지된다.

구독/쓰기 등 응답이 필요한 GATT 작업은 완료 후 다음 작업을 수행한다. 재연결 때 session_id를 다시 얻고 구독·설정·arm을 복구한다. 이전 session의 명령을 재사용하지 않는다. 연결이 끊긴 동안 발생한 모든 오디오를 저장·재전송하는 기능은 기본 범위에 없다.

## 오디오 형식

기본 profile_id=1: 16kHz mono, 20ms당 320 samples, 프로젝트 전용 독립 IMA 계열 ADPCM4 블록이다. ADPCM 본문 164 bytes + 패킷 헤더 16 bytes = Notify 값 180 bytes이며 큰 소리가 지속될 때 초당 50개, 72kbps다. BLE 프로토콜 비용은 추가된다.

헤더의 멀티바이트 값은 little-endian이다.

| offset | 필드 | 타입 |
|---|---|---|
| 0 | version=1 | u8 |
| 1 | kind=1 | u8 |
| 2 | flags | u8 |
| 3 | profile_id | u8 |
| 4 | stream_id | u16 |
| 6 | frame_seq | u16 |
| 8 | first_sample_index | u32 |
| 12 | frame_bytes | u16 |
| 14 | fragment_offset | u16 |

flags: bit0 MOTOR_ACTIVE, bit1 DISCONTINUITY, bit2 BURST_START, bit3 BURST_END, bit4 PRE_ROLL. 모터가 움직이는 동안에도 소리 기준을 만족하면 오디오가 전송된다.

ADPCM 본문: 첫 PCM 샘플 signed16 LE 2 bytes, 초기 step index 1 byte(0..88), reserved=0 1 byte, 이후 319개 샘플의 4-bit 코드 160 bytes. 코드 순서는 low nibble 먼저이며 마지막 high nibble은 0 padding이다. 각 블록은 독립 해독한다. WAV IMA나 RTP DVI4 블록과 같은 포장이라고 가정하지 않는다. 구현 단계에서 제공할 golden vectors로 해독을 대조한다.

기본 감지는 10ms RMS를 5ms마다 평가한다. 초기 시작 -45dBFS, 종료 -50dBFS, 종료 hold 500ms, pre-roll 최대 100ms다. dBFS는 디지털 상대 크기이며 실제 음압 dB SPL이 아니다. 조용한 구간은 전송하지 않는다. sample_index는 연속 감시 시간축이므로 burst 사이의 점프를 전송 손실로 해석하지 않는다. frame_seq는 전송 대상으로 선택한 프레임에만 부여한다.

## 명령 형식

공통 8-byte 헤더: `version:u8=1, opcode:u8, command_id:u16, session_id:u32`. 멀티바이트는 little-endian이다. 전체 명령은 20 bytes 이하다.

| opcode | 이름 | payload |
|---|---|---|
| 0x01 | GET_STATE | 없음. session_id=0 허용 |
| 0x02 | START_AUDIO | profile_id:u8 |
| 0x03 | STOP_AUDIO | 없음 |
| 0x04 | SET_DETECTION | on_dbfs_x100:i16, off_dbfs_x100:i16, hold_ms:u16, pre_roll_ms:u16 |
| 0x10 | PLAY_PATTERN | pattern_id:u8, strength:u8, repeat:u8, reserved:u8=0, ttl_ms:u16 |
| 0x11 | STOP_HAPTIC | 없음 |
| 0x20 | HEARTBEAT | 없음 |

PLAY_PATTERN: strength 1..100, repeat 1..10, ttl 1..5000ms. 패턴 ID는 SINGLE=1, DOUBLE=2, LONG=3, RAMP=4, SOS=5다. 전체 반복 길이가 ttl을 넘으면 거부한다. 강도는 논리값이며 전압이 아니다. 실행 중 새 PLAY는 BUSY이며 교체는 STOP 후 PLAY한다.

SET_DETECTION: 두 크기 값은 -9000..0(= -90..0dBFS), off <= on-300, hold 0..5000ms, pre-roll 0..100ms의 20ms 단위다. DISARMED 상태에서 변경한다.

예제는 **session_id가 0x12345678일 때**의 바이트다. 실제 연결에서는 GET_STATE로 얻은 session_id를 사용한다. 아래 명령 ID는 서로 다르며 정상 흐름을 따라 보낸다고 가정한다.

```text
상태 조회, command_id=1:
01 01 01 00 00 00 00 00

감지 설정(-45/-50dBFS, hold=500ms, pre-roll=100ms), command_id=2:
01 04 02 00 78 56 34 12 6C EE 78 EC F4 01 64 00

자동 감지 전송 활성화(profile=1), command_id=3:
01 02 03 00 78 56 34 12 01

heartbeat, command_id=4:
01 20 04 00 78 56 34 12

DOUBLE, strength=80, repeat=1, ttl=2000ms, command_id=5:
01 10 05 00 78 56 34 12 02 50 01 00 D0 07

진동 즉시 중지, command_id=6:
01 11 06 00 78 56 34 12
```

GATT write 성공과 실제 명령 실행 성공을 구분한다. Event의 공통 헤더는 명령과 같으며 opcode/command_id가 원본 명령을 가리킨다. 뒤에 `status:u8, detail:u8, device_ms:u32`가 온다. status는 ACCEPTED=1, STARTED=2, COMPLETED=3, STOPPED=4, REJECTED=5다. GET_STATE는 stream_id:u16, state_flags:u8, profile_id:u8를 추가해 총 18 bytes다. START_AUDIO의 STARTED는 stream_id:u16, capture_epoch_ms:u32를 추가해 총 20 bytes다.

동일 session/command_id/바이트를 재시도해도 보드는 진동을 다시 실행하지 않고 최신 결과를 반환한다. 다른 내용의 명령에 같은 ID를 재사용하지 않는다. 모터는 STOP, 연결 해제, ttl 만료, heartbeat lease 만료에서 꺼진다.

## 인수 확인 항목

휴대폰 측은 실제 MTU, Notify 연속 수신, 프레임 해독, 명령 결과, heartbeat, 재연결을 검증한다. 보드 프로젝트의 PC BLE 시험은 보드 측 동작을 검증하며 실제 휴대폰 백그라운드 동작을 보장하는 결과로 취급하지 않는다. 앱의 화면·분석·재생·권한·백그라운드 연결 유지는 외부 담당이다.
