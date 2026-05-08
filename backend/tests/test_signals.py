from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_calculate_signal_returns_ai_mode_and_new_bounds() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/signals/calculate",
            json={
                "north": 12,
                "south": 8,
                "east": 6,
                "west": 4,
                "is_peak_hour": False,
                "bus_directions": [],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "ai"
    assert 12 <= body["north"] <= 90
    assert 12 <= body["south"] <= 90
    assert 12 <= body["east"] <= 90
    assert 12 <= body["west"] <= 90


def test_calculate_signal_applies_bus_bonus_to_direction() -> None:
    with TestClient(app) as client:
        baseline_response = client.post(
            "/api/signals/calculate",
            json={
                "north": 5,
                "south": 5,
                "east": 5,
                "west": 5,
                "is_peak_hour": False,
                "bus_directions": [],
            },
        )
        bus_response = client.post(
            "/api/signals/calculate",
            json={
                "north": 5,
                "south": 5,
                "east": 5,
                "west": 5,
                "is_peak_hour": False,
                "bus_directions": ["north"],
            },
        )

    assert baseline_response.status_code == 200
    assert bus_response.status_code == 200

    baseline = baseline_response.json()
    with_bus = bus_response.json()

    assert with_bus["north"] > baseline["north"]


def test_calculate_signal_zero_vehicles_balances_cycle() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/signals/calculate",
            json={
                "north": 0,
                "south": 0,
                "east": 0,
                "west": 0,
                "is_peak_hour": False,
                "bus_directions": [],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["north"] == body["south"] == body["east"] == body["west"]


def test_calculate_signal_rejects_invalid_bus_direction() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/signals/calculate",
            json={
                "north": 1,
                "south": 1,
                "east": 1,
                "west": 1,
                "is_peak_hour": False,
                "bus_directions": ["northeast"],
            },
        )

    assert response.status_code == 422
