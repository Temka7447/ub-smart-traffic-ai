from __future__ import annotations

DIRECTIONS = ("north", "south", "east", "west")

BOX_X1, BOX_Y1 = 180.0, 130.0
BOX_X2, BOX_Y2 = 320.0, 270.0

LANE_X: dict[str, list[float]] = {
    "north": [220.0, 235.0],
    "south": [265.0, 280.0],
}
LANE_Y: dict[str, list[float]] = {
    "east": [220.0, 235.0],
    "west": [165.0, 180.0],
}

CROSSWALK_OFFSET = 18.0
STOP_LINE_OFFSET = 30.0

STOP_LINE = {
    "north": BOX_Y1 - STOP_LINE_OFFSET,
    "south": BOX_Y2 + STOP_LINE_OFFSET,
    "east": BOX_X1 - STOP_LINE_OFFSET,
    "west": BOX_X2 + STOP_LINE_OFFSET,
}

SAFE_GAP = 90.0
SPAWN_CLEAR = 96.0

MIN_GREEN = 12
MAX_GREEN = 90
CYCLE_TOTAL = 160
PEAK_MULTIPLIER = 1.6

VEHICLE_WEIGHTS: dict[str, float] = {
    "car": 1.0,
    "truck": 1.5,
    "bus": 2.0,
    "emergency": 10.0,
}


def calculate_green_time(
    vehicle_counts: dict[str, int],
    is_peak_hour: bool = False,
    bus_directions: list[str] | None = None,
    emergency_directions: list[str] | None = None,
    vehicle_type_counts: dict[str, dict[str, int]] | None = None,
) -> dict[str, int]:
    bus_dirs = set(bus_directions or [])
    emerg_dirs = set(emergency_directions or [])

    if emerg_dirs:
        return {direction: (MAX_GREEN if direction in emerg_dirs else MIN_GREEN) for direction in DIRECTIONS}

    scores: dict[str, float] = {}
    for direction in DIRECTIONS:
        count = max(0, vehicle_counts.get(direction, 0))

        if vehicle_type_counts and direction in vehicle_type_counts:
            type_counts = vehicle_type_counts[direction]
            weighted = sum(type_counts.get(vt, 0) * w for vt, w in VEHICLE_WEIGHTS.items())
        else:
            weighted = float(count)

        score = weighted * (PEAK_MULTIPLIER if is_peak_hour else 1.0)
        if direction in bus_dirs:
            score += 15.0
        scores[direction] = max(score, 0.1)

    total = sum(scores.values()) or 1.0
    return {
        direction: int(max(MIN_GREEN, min(MAX_GREEN, (score / total) * CYCLE_TOTAL)))
        for direction, score in scores.items()
    }


def should_yield(
    vehicle_dir: str,
    active_dir: str,
    vehicle_x: float,
    vehicle_y: float,
) -> bool:
    if vehicle_dir == active_dir:
        return False

    approach = 70.0

    if vehicle_dir == "north":
        return (BOX_Y1 - approach) <= vehicle_y < BOX_Y1
    if vehicle_dir == "south":
        return BOX_Y2 < vehicle_y <= (BOX_Y2 + approach)
    if vehicle_dir == "east":
        return (BOX_X1 - approach) <= vehicle_x < BOX_X1
    if vehicle_dir == "west":
        return BOX_X2 < vehicle_x <= (BOX_X2 + approach)

    return False


def get_safe_speed(
    vehicle: dict,
    same_lane_vehicles: list[dict],
    base_speed: float = 2.5,
) -> float:
    """
    Урдаа яваа машинтай зайг хэмжиж аюулгүй хурд буцаана.

    base_speed=1.0 гэж дуудвал 0.0–1.0 харьцаа буцаана,
    ингэснээр дуудагч dynamics["cruise"]-тэй шууд үржүүлж болно.

    Gap тооцоо:
        gap <= hard_stop (18px) → 0.0  (бүрэн зогс)
        gap <  SAFE_GAP  (90px) → квадрат ratio-р бууруулна
        gap >= SAFE_GAP         → base_speed (бүтэн хурд)
    """
    vehicle_dir = vehicle["dir"]
    vehicle_x = float(vehicle["x"])
    vehicle_y = float(vehicle["y"])

    min_gap = float("inf")
    for other in same_lane_vehicles:
        # Эргэлтийн дунд байгаа машинуудыг тооцохгүй
        if other.get("turnProgress", 0.0) > 0.05:
            continue

        other_x = float(other["x"])
        other_y = float(other["y"])

        if vehicle_dir == "north":
            gap = other_y - vehicle_y
        elif vehicle_dir == "south":
            gap = vehicle_y - other_y
        elif vehicle_dir == "east":
            gap = other_x - vehicle_x
        else:
            gap = vehicle_x - other_x

        if 0 < gap < SAFE_GAP * 2.5:
            min_gap = min(min_gap, gap)

    if min_gap == float("inf"):
        return base_speed

    hard_stop = 18.0

    if min_gap <= hard_stop:
        return 0.0

    if min_gap < SAFE_GAP:
        ratio = (min_gap - hard_stop) / (SAFE_GAP - hard_stop)
        return round(base_speed * ratio * ratio, 3)

    return base_speed