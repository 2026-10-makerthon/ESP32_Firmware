# 코딩 도구용 시작 지시 — 보드 펌웨어와 BLE API

> 초기 작업 지시를 보존한 문서입니다. 현재 구현·실행 방법은 README.md, 고정 계약은 contracts/protocol.md, 검증 상태는 docs/STATUS.ko.md가 기준입니다.

아래 내용을 프로젝트의 시작 작업 지시로 사용한다. 상세 계약은 HARNESS_DESIGN.ko.md, 외부 연동 요약은 BLE_INTERFACE.ko.md를 기준으로 한다.

---

XIAO ESP32-S3 + INMP441 + ELB060416 장치의 펌웨어, BLE 송수신 API, PC 테스트 하네스를 구현하라. **휴대폰 앱은 작업 범위에 포함하지 않는다. Android/Kotlin 프로젝트, 앱 화면, 모바일 SDK를 만들지 말라.** 목표는 설정 크기 이상의 소리가 감지될 때마다 BLE로 실시간 음성을 외부 휴대폰 클라이언트에 자동 전달하면서 휴대폰이 지정한 강도/패턴의 진동을 보드에서 독립 실행하는 것이다. 큰 소리가 계속되면 전송도 계속 유지하라.

먼저 HARNESS_DESIGN.ko.md를 읽고 통신 규격을 contracts/protocol.md에 고정하라. 문서에 없는 전압·전류·모터 종류·3.3V 입력 호환·PWM 주파수를 추정해서 확정하지 말라. 하드웨어 자료가 부족해도 mock과 순수 코어 구현은 진행하라.

기술 선택:

* 펌웨어: ESP-IDF C/C++, NimBLE, standard I2S DMA, LEDC PWM.
* 하네스: Python 참조 구현, 가짜 시간/장치, C/Python 교차 벡터, PC BLE 테스트 클라이언트.
* 외부 연동 산출물: UUID, 패킷 계약, 명령/응답 예제, ADPCM 공통 벡터, 연결 순서, 오류/복구 조건.
* 정확한 SDK/의존성 버전을 빌드 확인 후 잠그고 기록하라.

변경 불가 기본 계약:

* 서비스/특성 UUID, opcode, 바이트 순서는 설계 문서와 같아야 한다.
* 기본 음성은 16kHz mono, 20ms, 320 PCM samples이며 독립 ADPCM 블록으로 전송한다.
* 보드는 계속 소리 크기를 감시한다. 감지 기준은 gain/AGC 전 신호의 10ms RMS를 5ms마다 계산한 dBFS이며, 음성만 고르는 VAD가 아니다.
* 초기 튜닝값은 시작 -45dBFS, 종료 -50dBFS, 종료 hold 500ms, pre-roll 최대 100ms다. BLE 명령으로 설정 가능하게 하며 실제 음압 dB SPL로 단정하지 말라.
* 유효 연결/구독 후 외부 클라이언트가 SET_DETECTION과 START_AUDIO(arm)를 자동 호출하는 계약이다. 보드는 감지 이벤트마다 새 START_AUDIO를 요구하지 않는다.
* BURST_START/BURST_END/PRE_ROLL과 sample_index로 burst를 구분하고, 조용해서 생략한 구간을 패킷 손실로 세지 말라. 인접 burst에서 이미 보낸 pre-roll을 중복 전송하지 말라.
* 진동 중에도 크기 기준을 만족하는 오디오를 전송하되 MOTOR_ACTIVE로 표시하라. 자기 진동에 대한 분석→진동 재귀 제어는 별도로 처리하라.
* 4-bit × 16kHz mono의 코드율은 64kbps지만 독립 블록 본문은 65.6kbps, 전송 헤더 포함은 72kbps다. BLE 추가 비용과 평균 전송 duty는 별도로 계산하라.
* Audio Notify, Control Write with response, Event Indicate를 분리한다.
* PC BLE 테스트 클라이언트는 응답이 필요한 GATT 작업을 직렬로 처리한다. 휴대폰 내부 구현은 요구하지 않는다.
* 제공 API는 Audio Notify, Control Write, Event Indicate, Capabilities Read다. HTTP URL이나 앱 내부 API를 구현하는 작업으로 바꾸지 말라.
* 음성 송신의 지연이 명령 수신이나 모터 STOP 처리를 막지 않아야 한다.
* 보드는 패턴을 실행하고, 앱이 펄스마다 on/off를 보내게 만들지 말라.
* 모든 오디오 큐는 유한해야 한다. 혼잡 시 오래된 프레임을 버리고 실시간성을 유지한다.
* 재연결 시 세션을 교체하고 이전 패턴·미완성 프레임을 폐기한다.
* 부팅/오류/disconnect/TTL/heartbeat lease 만료에서 PWM OFF를 보장한다.
* 진동 출력 활성화는 확인된 hardware profile이 있을 때만 허용한다.
* ADPCM을 무손실로 취급하거나 압축 전후 PCM 일치를 합격 기준으로 쓰지 말라.

작업은 아래 순서로 진행하라. 이번에 수행할 단계와 검증 결과를 간결하게 기록하고 실패를 수정한 뒤 다음 단계로 간다.

1. firmware/, contracts/, harness/, hardware/, docs/ 구조와 protocol.md, patterns.json, hardware profile 초안, versions.lock 틀을 만든다. Capabilities 바이트 구조·오류 detail 숫자·state_flags 등 빠진 값은 계약 gate에서 확정하고 문서/벡터에 같이 반영한다.
2. Python 참조 파서/ADPCM/스케줄러와 golden vectors를 만든다. 수동 검산한 최소 벡터와 출처를 포함한다.
3. C 순수 코어를 구현하고 Python 참조와 같은 벡터로 교차 검증한다.
4. 소리 감지 경계/충격음/연속 큰 소리/hold/pre-roll과 가짜 BLE 손실/중복/지연/큐 포화/세션 교체/시간 wrap/STOP/lease 시험을 구현한다.
5. 펌웨어를 빌드하고 I2S·BLE·PWM 드라이버를 순수 코어에 연결한다.
6. PC BLE 클라이언트로 검색·연결·구독·설정·arm·오디오 수신/해독·진동/정지·heartbeat를 검증한다. 외부 담당에게 전달할 UUID·패킷 예제·해독 벡터를 정리한다.
7. 실제 장비가 있으면 마이크 단독→가짜 오디오 BLE→진동 보정→동시 통합 순서로 검증한다.
8. 30분 내구성, 지연, 누락률, 재연결, heartbeat 중단 시험 결과를 reports에 남긴다.

실장비가 없으면 하네스와 빌드 검증을 끝까지 진행하고 실장비 시험을 미검증으로 표시하라. 테스트용 mock 결과를 실제 성능으로 쓰지 말라. PC 결과를 실제 Android 결과로 쓰지 말라. 외부 앱 미제공을 이유로 보드 측 작업을 멈추거나 앱 개발을 시작하지 말라. 장비 식별이 불분명하면 연결된 임의 장치에 플래시하지 말라.

최종 보고에는 구현된 보드 기능, 실행한 테스트, 정확한 결과, 미확정 하드웨어 값, 아직 실행하지 못한 보드 시험, 외부 휴대폰 통합 미검증을 구분하라. 설계에서 제안한 CLI를 실제로 구현하기 전에는 실행 가능하다고 설명하지 말라.

이번 작업의 첫 산출물은 **계약·참조 구현·golden vectors가 검증되는 Gate A**다. 통합 코드를 한 번에 생성하기 전에 이 gate를 완성하라.
