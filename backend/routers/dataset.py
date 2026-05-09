from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from backend.services.dataset_service import get_loader

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


def _loader():
    try:
        return get_loader()
    except RuntimeError as e:
        raise HTTPException(503, detail=str(e))


@router.get("/summary")
async def summary() -> dict[str, Any]:
    return _loader().summary_statistics()


@router.get("/intersections")
async def intersections() -> dict[str, Any]:
    l = _loader()
    return {"ids": l.intersection_ids, "names": l.get_intersection_names()}


@router.get("/snapshot/{intersection_id}")
async def snapshot(
    intersection_id: int,
    timestamp: str | None = None,
    peak_only: bool   = False,
    heaviest:  bool   = False,
) -> dict[str, Any]:
    loader = _loader()
    if heaviest:
        snap = loader.get_heaviest_peak_snapshot(intersection_id)
    elif peak_only:
        snap = loader.get_latest_peak_snapshot(intersection_id)
    elif timestamp:
        snap = loader.get_snapshot(intersection_id, timestamp)
    else:
        snap = loader.get_latest_snapshot(intersection_id)

    if snap is None:
        raise HTTPException(404, detail=f"intersection_id={intersection_id} олдсонгүй.")

    return {**snap.to_simulator_state(), "load_factors": snap.get_load_factors()}


@router.get("/congestion-by-hour")
async def congestion_by_hour(peak_only: bool = False) -> dict[str, Any]:
    loader = _loader()
    data   = loader.peak_congestion_by_hour() if peak_only else loader.congestion_by_hour()
    return {"data": data, "peak_only": peak_only}


@router.get("/top-congested")
async def top_congested(n: int = 5) -> dict[str, Any]:
    return {"data": _loader().top_congested_intersections(n=n)}


@router.get("/weather-impact")
async def weather_impact() -> dict[str, Any]:
    return {"data": _loader().weather_impact_analysis()}


@router.get("/signal-efficiency")
async def signal_efficiency() -> dict[str, Any]:
    return _loader().signal_efficiency()


@router.get("/peak-vs-normal")
async def peak_vs_normal() -> dict[str, Any]:
    return _loader().peak_vs_normal_comparison()


@router.post("/load-to-simulator/{intersection_id}")
async def load_to_simulator(
    intersection_id: int,
    request:         Request,
    use_peak_data:   bool = False,
    use_heaviest:    bool = False,   # ← хамгийн ачаалалтай хэмжилт
) -> dict[str, Any]:
    loader = _loader()
    config = loader.get_simulator_config(
        intersection_id,
        use_peak_data = use_peak_data or use_heaviest,
        use_heaviest  = use_heaviest,
    )
    if not config:
        raise HTTPException(404, detail="Уулзвар олдсонгүй.")

    sim = request.app.state.simulator
    async with sim._lock:
        sim.queues                  = config["initial_queues"]
        sim.lane_queues             = sim._create_initial_lane_queues(config["initial_queues"])
        sim.green_times             = config["green_times"]
        sim.peak_hour               = config.get("peak_hour", False)
        sim.bus_directions          = config.get("bus_directions", [])
        sim._weather_speed_factor   = config.get("weather_factor", 1.0)

        # Оргил үеийн нэмэлт симуляторын параметрүүд
        if config.get("peak_load_applied"):
            sim._peak_arrival_rate  = config.get("arrival_rate",  0.95)
            sim._peak_spawn_chance  = config.get("spawn_chance",  0.95)
            sim._max_active_vehicles= config.get("max_vehicles",  120)
            sim._discharge_rate     = config.get("discharge_rate", 4)

    label = "хамгийн ачаалалтай" if use_heaviest else "оргил" if use_peak_data else "сүүлийн"
    return {
        "ok":          True,
        "loaded":      config,
        "load_factors": config.get("load_factors", {}),
        "message": (
            f"{config.get('intersection_name','?')} уулзварын "
            f"{label} өгөгдлийг ачааллыг нэмэгдүүлэн симуляторт ачааллаа."
        ),
    }