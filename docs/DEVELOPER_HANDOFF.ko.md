# 다른 개발자에게 전달할 연동 안내

2026-10-31 Codex 인수인계: 최신 맥락은 루트 `CONTEXT_HANDOFF.ko.md`,새 PC 시작 절차는 `START_HERE.ko.md`를 먼저 읽는다. 현재 XIAO 펌웨어에는3초 전원/6초 본딩 버튼과 DM161의3V 목표 초기 실제 출력 모드가 있다. 이 문서의 이전 배포 패키지 안내보다 `sound-haptic-codex-handoff-2026-10-31.zip`의 현재 요약을 우선한다.

이 패키지를 전달받으면 실제 마이크·진동 부품이 없어도 오디오 분석과 BLE 클라이언트 파트를 개발할 수 있습니다. 프로토콜 버전은1.0입니다. 이 문서는 시작 안내이며 바이트 수준의 최종 기준은 `contracts/protocol.md`입니다.

## 먼저 전달할 것

`dist/sound-haptic-devkit-v1.0.0.zip`을 전달하세요. 전체 소스, 설치 스크립트, 고정 규격과 벡터, 예제 패킷과 WAV, 검증 보고서가 포함됩니다. 로컬 가상환경/SDK/캐시와 실장비에서 수집한 사적 오디오는 포함하지 않습니다. 공개 저장소나 클라우드에 자동 업로드하지 않습니다.

## 담당별 시작점

| 담당 | 필요한 자료 | 지금 가능한 개발 |
|---|---|---|
| 휴대폰 BLE | protocol.md의 연결 순서·UUID·Control/Event | 검색·구독·세션·진동 명령·복구 구현 |
| 오디오 해독 | golden_vectors.json, harness/codec.py | ADPCM을 담당 언어로 해독하고 고정 PCM과 비교 |
| 소리 분석 | examples/received.wav, packets.jsonl | 프레임 수신 후 분석 파이프라인, gap/MOTOR_ACTIVE 처리 |
| 펌웨어·모듈 | firmware/, hardware/profiles/ | 마이크·구동 모듈 어댑터 교체 |
| 통합·QA | tests/, harness/reports/, HIL_CHECKLIST.ko.md | 손실·중복·정지·재연결·실물 측정 |

분석 함수에는 복원된 PCM과 sample_rate/sample_index/flags를 넘기세요. 분석 결과가 진동으로 이어지면 모터 진동에 반응하는 재귀를 막기 위한 cooldown/자기 진동 정책을 구현해야 합니다. MOTOR_ACTIVE 동안의 소리도 기본적으로 전달됩니다.

## 10분 시작 절차

1. ZIP을 풀고 `README.md`의 setup 명령을 실행합니다. 이 PC에서는 기존 `.venv`를 바로 사용합니다.
2. `python -m harness demo`를 실행하고 WAV와 JSONL을 확인합니다. 이는 오프라인 가상 장치이며 PC가 BLE 주변 장치로 광고되는 것은 아닙니다.
3. JSONL의 각 hex를 raw bytes로 읽습니다. kind가 control/event/audio이며 at_ms는 가짜 장치 시간입니다. 실제 WAV 형식의 IMA 블록으로 해석하면 안 됩니다.
4. `golden_vectors.json`의 input_pcm을 인코딩하면 block_hex, block_hex를 해독하면 decoded_pcm과 정확히 일치해야 합니다. 입력 PCM과 해독 PCM은 손실 압축 때문에 다를 수 있습니다. 첫 minimal vector는 수동 검산되어 있습니다.
5. 실제 보드가 준비되면 서비스 UUID로 연결하고 아래 순서대로 수행합니다.

```text
Capabilities Read → Event Indicate 구독 → GET_STATE(session=0)
→ 실제 MTU 확인 → Audio Notify 구독 → SET_DETECTION → START_AUDIO
→ ACCEPTED → STARTED(stream_id,capture_epoch_ms)
→ Audio 재조립/해독 → 분석
HEARTBEAT(500ms 주기) → PLAY_PATTERN → STARTED/COMPLETED 확인
중지: STOP_HAPTIC → STOPPED 확인
```

시작 전 GET_STATE로 받은 session_id를 모든 명령에 넣으세요. 예제의0x12345678은 설명용입니다. GATT 쓰기 성공만으로 진동 성공이라고 표시하지 마세요. 명령 ID에 맞는 Event를 확인해야 합니다. START_AUDIO의 STARTED는 조용한 상태에서도 첫 프레임 수집 후 발생합니다.

## 최소 Python 사용 예

프로젝트 루트에서 실행하는 예제입니다. 이 호출은 raw bytes를 생성할 뿐 무선으로 전송하지 않습니다.

```python
from harness.protocol import Command, Op, Event, Reassembler
from harness.codec import pcm

session_from_get_state = 0x12345678  # 실제 연결에서는 GET_STATE Event로 교체
play = Command(Op.PLAY_PATTERN, 5, session_from_get_state, (2,80,1,0,2000)).encode()
assert play.hex() == '011005007856341202500100d007'

# Event.decode(event_bytes)로 실행 결과를 확인합니다.
# STARTED에서 받은 stream_id로 receiver.reset(stream_id)를 호출합니다.
receiver = Reassembler()
# frame = receiver.push(notification_bytes, monotonic_ms)
# if frame is not None:
#     samples = pcm(frame)  # signed PCM16 리스트
```

Python 의존성 없이도 계약을 다른 언어로 구현할 수 있습니다. Python 클래스는 참고용 구현이며 휴대폰 앱용 SDK나 UI는 제공하지 않습니다.

## 꼭 맞춰야 하는 동작

- 기본 오디오는16kHz mono,20ms/320samples, 독립 ADPCM164bytes입니다. 전송 헤더16bytes를 제거하고, low nibble부터 해독합니다.
- 수신 재조립은 연결 세대/stream_id/frame_seq로 구분하고100ms 이상 미완성 프레임을 버립니다. 큐는 유한하게 둡니다.
- BURST_START에서 이전 지터 버퍼를 비웁니다. sample_index의 조용한 구간 점프는 손실이 아닙니다. frame_seq의 누락과 구분합니다.
- 기본100ms pre-roll과 현재 프레임이5프레임 송신 큐를 초과하면 오래된 pre-roll이 버려질 수 있습니다. 데모의 dropped/lost는 보고서에 그대로 표시됩니다.
- HEARTBEAT는 실행 명령 replay cache와 별도로 처리됩니다. 늦게 도착해도 중단된 진동은 재개되지 않습니다.
- 연결이 끊기면 재조립/진동/세션을 폐기합니다. 다시 연결해서 구독·설정·arm을 반복합니다.
- simulation capability를 확인하세요. 명령 성공이나 MOTOR_ACTIVE 표시가 실제 모터 동작을 증명하지는 않습니다.
- 현재 XIAO 펌웨어는6초 부팅으로120초 본딩 등록을 허용하고,저장 기기와 암호화된 연결에서 앱 데이터를 사용합니다. Just Works는MITM 인증을 제공하지 않습니다. 제품 환경의 권한·백그라운드 정책은 별도 통합 대상입니다.

Android 권한·백그라운드 연결·실제 폰의 MTU/처리량은 앱 담당자가 확인합니다. PC BLE 검증과 Android 검증은 서로 다른 결과입니다. 표준 Bluetooth 마이크를 요구하는 기능과 이 전용 GATT 오디오 서비스를 혼동하지 마세요.

## 인수 기준

담당 언어에서 모든 golden vector가 일치하고, 진동 명령의 정상/거부/중복·재연결 처리가 맞아야 합니다. 실장비에서는30분 연속 소리·동시 진동·STOP·heartbeat 중단·재연결 시험을 수행하고 측정 조건과 로그를 함께 남깁니다. 초기 목표와 절차는 `HIL_CHECKLIST.ko.md`에 있습니다.
