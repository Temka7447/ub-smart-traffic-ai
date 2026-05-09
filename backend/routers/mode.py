from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from backend.models.intersection import SimulationState
from backend.services.ai_runtime_manager import normalize_mode
from backend.services.simulator import TrafficSimulator

router = APIRouter(prefix="/api", tags=["mode"])


class ModeSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str


def get_simulator(request: Request) -> TrafficSimulator:
    return request.app.state.simulator


@router.post("/mode", response_model=SimulationState)
async def switch_mode(
    payload: ModeSwitchRequest,
    simulator: TrafficSimulator = Depends(get_simulator),
) -> SimulationState:
    try:
        mode = normalize_mode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await simulator.set_mode(mode)


@router.get("/mode")
async def get_mode(
    simulator: TrafficSimulator = Depends(get_simulator),
) -> dict[str, str]:
    state = await simulator.get_state()
    return {
        "mode": state.mode,
        "label": "ai" if state.mode == "ai" else "traditional",
    }
