"""CAN 연결과 통신의 공통 기본값. 작업별 모터 설정은 실행 파일에 둔다."""

CAN_INTERFACE = "seeedstudio"
CAN_CHANNEL = "COM4"
CAN_BITRATE = 1_000_000
RESPONSE_TIMEOUT = 1.0
READ_RETRIES = 3
RETRY_DELAY = 0.2
