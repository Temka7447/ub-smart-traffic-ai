from __future__ import annotations


def calculate_green_time(
    vehicle_counts: dict[str, int],
    is_peak_hour: bool = False,
    bus_directions: list[str] = [],
) -> dict[str, int]:
    scores: dict[str, int] = {}
    for direction, count in vehicle_counts.items():
        score = count
        if is_peak_hour:
            score += 5
        if direction in bus_directions:
            score += 10
        scores[direction] = score

    total = sum(scores.values()) or 1
    return {
        direction: max(10, min(60, int((score / total) * 120)))
        for direction, score in scores.items()
    }
