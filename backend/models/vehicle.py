from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["north", "south", "east", "west"]
VehicleType = Literal["car", "bus", "truck", "emergency"]
TurnDirection = Literal["left", "straight", "right"]


class Vehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    dir: Direction
    type: VehicleType
    lane: int = Field(default=0, ge=0, le=1)
    turn: TurnDirection = "straight"
    x: float
    y: float
    speed: float = 0.0
    targetSpeed: float = 0.0
    angle: float = 0.0
    steer: float = 0.0
    suspension: float = 0.0
    turnProgress: float = 0.0
    turnStartX: float | None = None
    turnStartY: float | None = None
    turnEndX: float | None = None
    turnEndY: float | None = None
    turnFromDir: Direction | None = None
    turnToDir: Direction | None = None
    waiting: bool = False
    color: str
