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
    waiting: bool = False
    color: str
