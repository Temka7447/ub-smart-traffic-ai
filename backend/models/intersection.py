from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.models.vehicle import Direction, Vehicle

Mode = Literal["ai", "fixed"]
SignalState = Literal["green", "yellow", "all_red"]


class SignalCalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    north: int = Field(ge=0)
    south: int = Field(ge=0)
    east: int = Field(ge=0)
    west: int = Field(ge=0)
    is_peak_hour: bool = False
    bus_directions: list[str] = Field(default_factory=list)

    @field_validator("bus_directions")
    @classmethod
    def validate_bus_directions(cls, value: list[str]) -> list[str]:
        allowed = {"north", "south", "east", "west"}
        invalid = [direction for direction in value if direction not in allowed]
        if invalid:
            raise ValueError(f"Invalid bus_directions: {', '.join(invalid)}")
        return list(dict.fromkeys(value))


class SignalCalculationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    north: int = Field(ge=12, le=90)
    south: int = Field(ge=12, le=90)
    east: int = Field(ge=12, le=90)
    west: int = Field(ge=12, le=90)
    mode: Mode


class SimulationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode | None = None
    peak_hour: bool | None = None
    heavy_north: bool | None = None
    bus_directions: list[str] | None = None
    emergency_directions: list[str] | None = None
    reset: bool = False
    autostart: bool = True

    @field_validator("bus_directions", "emergency_directions")
    @classmethod
    def validate_priority_directions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        allowed = {"north", "south", "east", "west"}
        invalid = [direction for direction in value if direction not in allowed]
        if invalid:
            raise ValueError(f"Invalid bus_directions: {', '.join(invalid)}")
        return list(dict.fromkeys(value))


class SimulationSpeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multiplier: float = Field(ge=0.5, le=4.0)


class QueueHistoryPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: int
    queue: int


class IntersectionNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    row: int
    col: int
    label: str
    queues: dict[str, int]
    laneQueues: dict[str, int]
    activeDir: Direction
    timer: int
    signalState: SignalState
    greenTimes: dict[str, int]


class ComparisonStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    avgFixedWait: int
    avgAIWait: int
    fixedSamples: int
    aiSamples: int
    improvementPct: int
    totalPassed: int
    throughputPerMinute: float
    avgQueueDepth: float
    queueStability: int


class QueueHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history: list[QueueHistoryPoint]


class SimulationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    peakHour: bool
    heavyNorth: bool
    isRunning: bool
    speed: float
    activeDir: Direction
    phaseTimer: int
    signalState: SignalState
    queues: dict[str, int]
    laneQueues: dict[str, int]
    totalPassed: int
    waitTimes: dict[str, list[int]]
    vehicles: list[Vehicle]
    intersections: list[IntersectionNode]
    simTime: int
    history: list[QueueHistoryPoint]
    greenTimes: dict[str, int]
    avgFixedWait: int
    avgAIWait: int
    busDirections: list[str]
    emergencyDirections: list[str]
    kpis: dict[str, float]
