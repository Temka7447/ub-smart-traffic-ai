from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.models.intersection import ComparisonStats, QueueHistoryResponse
from backend.services.simulator import TrafficSimulator

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_simulator(request: Request) -> TrafficSimulator:
    return request.app.state.simulator


@router.get("/comparison", response_model=ComparisonStats)
async def get_comparison(
    simulator: TrafficSimulator = Depends(get_simulator),
) -> ComparisonStats:
    return await simulator.get_comparison_stats()


@router.get("/queue-history", response_model=QueueHistoryResponse)
async def get_queue_history(
    simulator: TrafficSimulator = Depends(get_simulator),
) -> QueueHistoryResponse:
    return await simulator.get_queue_history()
