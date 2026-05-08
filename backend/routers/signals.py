from __future__ import annotations

from fastapi import APIRouter

from backend.models.intersection import SignalCalculationRequest, SignalCalculationResponse
from backend.services.ai_controller import calculate_green_time

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.post("/calculate", response_model=SignalCalculationResponse)
async def calculate_signal(payload: SignalCalculationRequest) -> SignalCalculationResponse:
    vehicle_counts = {
        "north": payload.north,
        "south": payload.south,
        "east": payload.east,
        "west": payload.west,
    }
    result = calculate_green_time(
        vehicle_counts,
        is_peak_hour=payload.is_peak_hour,
        bus_directions=payload.bus_directions,
    )

    return SignalCalculationResponse(
        north=result["north"],
        south=result["south"],
        east=result["east"],
        west=result["west"],
        mode="ai",
    )
