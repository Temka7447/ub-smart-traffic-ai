"""
FastAPI Application — UB Smart Traffic AI Backend
==================================================
Endpoints:
  WS  /ws/simulation          — real-time simulation broadcast (1 Hz)
  POST /api/detection          — ingest YOLO detection from camera
  GET  /api/state              — full current state snapshot
  POST /api/emergency/{int_id} — trigger emergency mode
  POST /api/weather            — update weather condition
  GET  /api/metrics            — aggregated metrics for comparison panel
  GET  /api/intersections      — list all intersections with names
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .lane_state import VehicleType, WeatherCondition
from .simulator import TrafficSimulator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# APP LIFECYCLE
# ──────────────────────────────────────────────

simulator: Optional[TrafficSimulator] = None
_sim_task: Optional[asyncio.Task] = None
_ws_clients: set[WebSocket] = set()


async def _broadcast(payload: dict):
    """Broadcast simulation update to all connected WebSocket clients."""
    if not _ws_clients:
        return
    message = json.dumps(payload)
    disconnected = set()
    for ws in list(_ws_clients):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _ws_clients.difference_update(disconnected)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global simulator, _sim_task
    simulator = TrafficSimulator(comparison_mode=True)
    _sim_task = asyncio.create_task(simulator.run_async(broadcast_callback=_broadcast))
    logger.info("Simulator started")
    yield
    simulator.stop()
    if _sim_task:
        _sim_task.cancel()
    logger.info("Simulator stopped")


app = FastAPI(
    title="UB Smart Traffic AI",
    description="Adaptive traffic control for Ulaanbaatar intersections",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# WEBSOCKET
# ──────────────────────────────────────────────

@app.websocket("/ws/simulation")
async def ws_simulation(websocket: WebSocket):
    """
    Real-time simulation stream.
    Sends JSON every 1 second with all intersection states.
    """
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info(f"WS client connected. Total: {len(_ws_clients)}")
    try:
        # Send current state immediately on connect
        if simulator:
            await websocket.send_text(json.dumps(simulator.get_current_state()))
        # Keep alive
        while True:
            await websocket.receive_text()   # client can send commands here
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)
        logger.info(f"WS client disconnected. Total: {len(_ws_clients)}")


# ──────────────────────────────────────────────
# REQUEST MODELS
# ──────────────────────────────────────────────

class DetectionPayload(BaseModel):
    """
    Posted by the YOLO/OpenCV detection service.
    Matches the existing camera output format.
    """
    intersection_id: int
    lane_id: int                        # 1-16 (4 lanes × 4 directions)
    vehicle_count: int
    vehicle_types: list[str] = []       # ['car', 'bus', 'truck', 'emergency']
    queue_length: Optional[float] = None
    avg_speed: Optional[float] = None
    fps: float = 3.3


class WeatherPayload(BaseModel):
    condition: str   # 'Clear', 'Cloudy', 'Rain', 'Snow', 'Fog'


class PedestrianPayload(BaseModel):
    intersection_id: int
    crosswalk_id: str     # 'N', 'S', 'E', 'W'
    waiting_count: int


# ──────────────────────────────────────────────
# REST ENDPOINTS
# ──────────────────────────────────────────────

@app.post("/api/detection")
async def post_detection(payload: DetectionPayload):
    """
    Ingest YOLO lane detection from camera processing service.
    This is called by your existing detection pipeline (ai_controller ↔ YOLO bridge).
    """
    if not simulator:
        raise HTTPException(503, "Simulator not ready")

    simulator.ingest_camera_detection(
        intersection_id=payload.intersection_id,
        lane_id=payload.lane_id,
        vehicle_count=payload.vehicle_count,
        vehicle_types=payload.vehicle_types,
        queue_length=payload.queue_length,
        avg_speed=payload.avg_speed,
        fps=payload.fps,
    )
    return {"status": "ok"}


@app.get("/api/state")
async def get_state():
    """Full current simulation state (REST alternative to WebSocket)."""
    if not simulator:
        raise HTTPException(503, "Simulator not ready")
    return simulator.get_current_state()


@app.post("/api/emergency/{intersection_id}")
async def trigger_emergency(intersection_id: int, direction: str = "N"):
    """
    Manually trigger emergency vehicle priority at an intersection.
    In production this would be triggered by the YOLO emergency detection.
    """
    if not simulator or intersection_id not in simulator.ai_controllers:
        raise HTTPException(404, f"Intersection {intersection_id} not found")

    dir_map = {'N': 'NORTH', 'S': 'SOUTH', 'E': 'EAST', 'W': 'WEST'}
    from .lane_state import Direction
    direction_enum = Direction[dir_map.get(direction.upper(), 'NORTH')]

    simulator.ai_controllers[intersection_id].emergency_direction = direction_enum
    logger.warning(f"EMERGENCY triggered at INT-{intersection_id} direction={direction}")
    return {"status": "emergency_activated", "intersection": intersection_id}


@app.post("/api/weather")
async def update_weather(payload: WeatherPayload):
    """Update weather condition for all intersections."""
    if not simulator:
        raise HTTPException(503, "Simulator not ready")
    try:
        weather = WeatherCondition(payload.condition)
    except ValueError:
        raise HTTPException(400, f"Unknown weather: {payload.condition}")
    simulator.update_weather(weather)
    return {"status": "ok", "weather": weather.value}


@app.post("/api/pedestrian")
async def update_pedestrian(payload: PedestrianPayload):
    """Update pedestrian waiting count at a crosswalk."""
    if not simulator or payload.intersection_id not in simulator.ai_controllers:
        raise HTTPException(404)
    ctrl = simulator.ai_controllers[payload.intersection_id]
    if payload.crosswalk_id in ctrl.pedestrians:
        ctrl.pedestrians[payload.crosswalk_id].waiting_count = payload.waiting_count
    return {"status": "ok"}


@app.get("/api/intersections")
async def list_intersections():
    """List all intersections with names, positions, and current phase."""
    if not simulator:
        raise HTTPException(503)
    state = simulator.get_current_state()
    return {
        "intersections": [
            {
                "id": i,
                "name": ctrl.intersection_name,
                "grid_row": i // 3,
                "grid_col": i % 3,
                "ai_mode": ctrl.ai_mode,
                "current_phase": ctrl.current_phase.value,
            }
            for i, ctrl in simulator.ai_controllers.items()
        ]
    }


@app.get("/api/metrics")
async def get_metrics():
    """
    Aggregated metrics for the comparison panel (ComparisonChart.jsx).
    Returns last 100 metric snapshots.
    """
    if not simulator:
        raise HTTPException(503)
    history = simulator._metrics_history[-100:]
    return {"metrics": history, "count": len(history)}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "simulator_running": simulator.running if simulator else False,
        "tick": simulator._tick_count if simulator else 0,
        "ws_clients": len(_ws_clients),
    }
