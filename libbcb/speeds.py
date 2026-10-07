"""수동 입력 및 순차 파일에 공통으로 사용하는 속도 해석."""

def parse_speeds(command: str, *, max_rpm: int = 500) -> tuple[int, int, int, int]:
    """네 노드의 속도를 입력 순서대로 해석한다. 부호를 자동 변경하지 않는다."""
    parts = command.split()
    if len(parts) != 4:
        raise ValueError("속도 네 개를 공백으로 구분해 입력하세요: 속도1 속도2 속도3 속도4")
    try:
        targets = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"속도는 -{max_rpm}~{max_rpm} 범위의 정수여야 합니다") from exc
    if any(abs(target) > max_rpm for target in targets):
        raise ValueError(f"각 속도는 -{max_rpm}~{max_rpm} rpm이어야 합니다")
    return targets[0], targets[1], targets[2], targets[3]


def alternating_speeds(command: str, *, node_count: int, max_rpm: int) -> tuple[int, ...]:
    try:
        rpm = int(command)
    except ValueError as exc:
        raise ValueError("RPM 정수 또는 monitor / stop / resume / reset / status / clear / quit를 입력하세요") from exc
    if abs(rpm) > max_rpm:
        raise ValueError(f"속도 범위는 ±{max_rpm} rpm입니다")
    return tuple(rpm if index % 2 == 0 else -rpm for index in range(node_count))
