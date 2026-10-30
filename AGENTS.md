# 소리 전달 프로젝트 인수인계

새 환경에서는 `CONTEXT_HANDOFF.ko.md`를 먼저 읽고, 실제 작업에 필요한 `docs/XIAO_OPERATION.ko.md`, `docs/STATUS.ko.md`, `contracts/protocol.md`를 참고한다. 사용자와 한국어로 소통한다.

- 현재 하드웨어는 XIAO ESP32-S3 + INMP441 + DRV2605L + DM161 + GPIO7 버튼이다. SuperMini/EM-MA-126 문서는 이전 후보 기록이다.
- 핀은 WS1/BCLK2/SD4, SDA5/SCL6, 버튼7–GND다. 사용자 배선과 버튼3초 전원/6초 페어링 동작을 유지한다.
- 사용자는 DM161의3V 목표 초기 실제 출력 진행을 승인했다. `-PhysicalHaptic`은 `hardware/profiles/xiao-dm161-3v-prototype.json`을 선택한다. 물리 출력 허용과 실물 검증 완료 표시는 별개이며, 현재 VERIFIED=0이다. 기존 미확정 프로파일은 로그 전용 경로다.
- 모터는 DC ERM으로 가정한 상태다.3V/3.7V 표기와80mA는 사용자 제공 정보이며, 기동 최대전류나 실제 측정값으로 바꾸어 쓰지 않는다.
- BLE v1 UUID·opcode·패킷·ADPCM 형식을 유지한다. 상세 규격은 `contracts/protocol.md`가 기준이다. 기본 작업 범위는 보드·통신·PC 클라이언트이며 휴대폰 앱은 구현하지 않았다.
- 실행하지 않은 플래시·무선·전기·촉각·휴대폰 시험을 성공으로 기록하지 않는다. 보드에 쓰려면 대상 보드/포트를 식별하고 현재 사용자 요청에 따라 진행한다. 단순 맥락 읽기나 파일 확인만으로 업로드하지 않는다.
- 이전 PC의 S: 드라이브, 절대경로, `.venv`, SDK 설치 상태를 새 PC에서 사용할 수 있다고 가정하지 않는다. 새 PC 설정은 `START_HERE.ko.md`를 따른다.
- 관련 변경의 테스트를 실행하고 결과와 실물 미검증 범위를 기록한다. 사용자의 최신 지시가 이 문서보다 우선한다.
