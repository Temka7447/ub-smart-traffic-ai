from __future__ import annotations

from fastapi import APIRouter, Depends, Request, WebSocket

from backend.models.intersection import SimulationSpeedRequest, SimulationStartRequest, SimulationState
from backend.services.simulator import TrafficSimulator

router = APIRouter(prefix="/api/simulation", tags=["simulation"])
ws_router = APIRouter(tags=["simulation"])


def get_simulator(request: Request) -> TrafficSimulator:
    return request.app.state.simulator


@router.post("/start", response_model=SimulationState)
async def start_simulation(
    payload: SimulationStartRequest | None = None,
    simulator: TrafficSimulator = Depends(get_simulator),
) -> SimulationState:
    return await simulator.start(payload or SimulationStartRequest())


@router.post("/stop", response_model=SimulationState)
async def stop_simulation(
    simulator: TrafficSimulator = Depends(get_simulator),
) -> SimulationState:
    return await simulator.stop()


@router.post("/speed", response_model=SimulationState)
async def set_simulation_speed(
    payload: SimulationSpeedRequest,
    simulator: TrafficSimulator = Depends(get_simulator),
) -> SimulationState:
    return await simulator.set_speed(payload.multiplier)


@router.get("/state", response_model=SimulationState)
async def get_simulation_state(
    simulator: TrafficSimulator = Depends(get_simulator),
) -> SimulationState:
    return await simulator.get_state()


@ws_router.websocket("/ws/simulation")
async def simulation_websocket(websocket: WebSocket) -> None:
    simulator: TrafficSimulator = websocket.app.state.simulator
    await simulator.listen(websocket)
