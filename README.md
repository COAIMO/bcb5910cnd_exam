# bcb5910cnd_exam

## 공통 라이브러리

다른 위치에서는 `python Output/모터동작테스트.py 1`처럼 실행 파일 경로를 지정합니다.
파일을 다른 곳으로 복사할 때는 `cancommon`과 `libbcb` 폴더를 모두 실행 파일 옆에 함께 복사하세요.

라이브러리는 범용 CAN/CANopen 통신과 BCB 장치 제어로 구분합니다.
`libbcb`는 `cancommon`을 사용하며, `cancommon`은 장치 라이브러리에 의존하지 않습니다.

| 라이브러리 | 파일 | 역할 |
| --- | --- | --- |
| `cancommon` | `config.py` | CAN 포트, 통신 속도, 타임아웃 및 읽기 재시도 기본값 |
| `cancommon` | `bus.py` | CAN 어댑터 연결 |
| `cancommon` | `cli.py` | CAN 옵션, 노드 번호 검증 및 노드별 읽기 결과 처리 |
| `cancommon` | `sdo.py` | 일반 SDO 송수신, 응답 검증, 정수 읽기 및 단일 바이트 쓰기 |
| `libbcb` | `cli.py` | BCB 모터 운전 명령행 및 실행 오류 처리 |
| `libbcb` | `sdo.py` | 모터 쓰기의 ACK 누락 확인, 파라미터 재시도 및 저장 정책 |
| `libbcb` | `drive.py` | BCB 객체 주소, 초기화, 상태 확인, 비상정지 및 오류 리셋 |
| `libbcb` | `motion.py` | 수동/순차 운전, 명령 입력 및 상태/RPM 감시 |
| `libbcb` | `speeds.py` | 모터 속도 입력 해석 |

통신 옵션은 `cancommon/config.py`, 장치 파라미터 쓰기 재시도 횟수는
`libbcb/sdo.py`의 `WRITE_RETRIES`에서 관리합니다. 저장 명령은 한 번만 전송합니다.

각 실행 파일에는 작업별 설정값과 실행 로직을 둡니다. 모터 파라미터와 PI 게인은
`모터설정.py`, 변경할 ID는 `노드ID변경.py`, 속도 제한과 가감속 값은 각 모터 테스트
파일에서 수정합니다. 순차 운전은 `모터동작테스트seq.py`의 `SEQUENCE_INTERVAL`을 사용합니다.

하드웨어 연결 없이 검증하려면 `Output`에서 `python -m unittest discover -s tests -v`를 실행합니다.

## 모터제어기 상태 확인

```cmd
python 노드ID체크.py 1 2
python 노드ID위치.py 1 2

python 노드ID체크.py 3 4
python 노드ID위치.py 3 4

python 노드ID체크.py 1 2 3 4
python 노드ID위치.py 1 2 3 4
```

## 모터제어기 노드아이디 시작번호 변경

```cmd
python 노드ID변경.py 1 3
```

## 모터제어기 기본 설정적용(각 아이디별로 설정 필요)

```cmd
python 모터설정.py 1
python 모터설정.py 2

python 모터설정.py 3
python 모터설정.py 4
```

## 모터제어기 테스트

```cmd
python 모터동작테스트.py 1
```

시작 Node ID가 1이면 Node 1과 2를 사용합니다. 실행 후 RPM 정수를 입력하면
첫 노드는 입력값, 다음 노드는 반대 부호로 동작합니다. 입력 범위는 -500~500 rpm입니다.

- `stop`: 두 노드에 비상정지 요청
- `resume`: 오류가 없으면 비상정지 해제 (목표 속도 0 rpm)
- `status`: 상태와 오류 코드 다시 표시
- `quit`: 비상정지 요청 후 종료

가속, 감속, 비상정지 감속은 매뉴얼의 원시 DEC 값 `512`로 설정하며,
실행 중 두 노드의 상태와 오류 코드를 감시합니다.
