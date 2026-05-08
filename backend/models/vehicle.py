from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Direction = Literal["north", "south", "east", "west"]
VehicleType = Literal["car", "bus", "truck"]


class Vehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    dir: Direction
    type: VehicleType
    x: float
    y: float
    waiting: bool = False
    color: str
