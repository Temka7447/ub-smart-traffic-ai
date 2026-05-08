from __future__ import annotations

DIRECTIONS = ("north", "south", "east", "west")

BOX_X1, BOX_Y1 = 180.0, 130.0
BOX_X2, BOX_Y2 = 320.0, 270.0

LANE_X: dict[str, list[float]] = {
    "north": [220.0, 235.0],
    "south": [265.0, 280.0],
}
LANE_Y: dict[str, list[float]] = {
    "east": [165.0, 180.0],
    "west": [220.0, 235.0],
}

STOP_LINE: dict[str, float] = {
    "north": BOX_Y1,
    "south": BOX_Y2,
    "east": BOX_X1,
    "west": BOX_X2,
}

SAFE_GAP = 58.0
SPAWN_CLEAR = 78.0

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
            weighted = sum(type_counts.get(vehicle_type, 0) * weight for vehicle_type, weight in VEHICLE_WEIGHTS.items())
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
    vehicle_dir = vehicle["dir"]
    vehicle_x = float(vehicle["x"])
    vehicle_y = float(vehicle["y"])
    min_gap = float("inf")

    for other in same_lane_vehicles:
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

    if min_gap < 12:
        return 0.0

    if min_gap < SAFE_GAP:
        ratio = (min_gap - 12) / (SAFE_GAP - 12)
        return round(base_speed * max(0.05, ratio), 2)

    return base_speed
