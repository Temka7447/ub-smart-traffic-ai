"""
Lane State Models — Ulaanbaatar AI Traffic Control System
=========================================================
Typed data structures for every layer of the traffic system.
These models bridge the YOLO detection output and the AI controller.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import time


# ──────────────────────────────────────────────
# ENUMS
# ──────────────────────────────────────────────

class LaneType(Enum):
    """
    Physical lane function at each approach arm.
    Matches the YOLO polygon zone labeling.
    """
    INCOMING_STRAIGHT_RIGHT = "L1"   # L1: straight + right combined
    INCOMING_LEFT_TURN      = "L2"   # L2: protected left-turn only
    OUTGOING_PRIMARY        = "L3"   # L3: outgoing main lane
    OUTGOING_SECONDARY      = "L4"   # L4: outgoing secondary lane


class Direction(Enum):
    NORTH = "N"
    SOUTH = "S"
    EAST  = "E"
    WEST  = "W"


class SignalState(Enum):
    GREEN  = "green"
    YELLOW = "yellow"
    RED    = "red"
    # Special states
    GREEN_LEFT   = "green_left"    # Protected left-turn arrow
    PEDESTRIAN   = "pedestrian"    # Ped walk signal active
    ALL_RED      = "all_red"       # Safety clearance buffer


class PhaseID(Enum):
    """
    Safe, conflict-free signal phases.
    Conflict matrix enforced by SignalPhaseManager.
    """
    NS_STRAIGHT    = "ns_straight"     # N+S straight+right simultaneously
    NS_LEFT        = "ns_left"         # N+S protected left turn
    EW_STRAIGHT    = "ew_straight"     # E+W straight+right simultaneously
    EW_LEFT        = "ew_left"         # E+W protected left turn
    PEDESTRIAN_NS  = "ped_ns"          # Ped crossing on N/S crosswalks
    PEDESTRIAN_EW  = "ped_ew"          # Ped crossing on E/W crosswalks
    ALL_RED        = "all_red"         # Interphase safety buffer


class VehicleType(Enum):
    CAR   = "car"
    BUS   = "bus"
    TRUCK = "truck"
    EMERGENCY = "emergency"  # Ambulance, police, fire


class WeatherCondition(Enum):
    CLEAR  = "Clear"
    CLOUDY = "Cloudy"
    RAIN   = "Rain"
    SNOW   = "Snow"
    FOG    = "Fog"


class TimeOfDayCategory(Enum):
    """Derived from UB dataset: rush at 07-09, 17-19, lunch 12-14."""
    NIGHT_QUIET   = "night_quiet"    # 20:00–06:00  avg CI ~0.25
    MORNING_RUSH  = "morning_rush"   # 07:00–09:00  avg CI ~0.72
    MID_MORNING   = "mid_morning"    # 09:00–12:00  avg CI ~0.47
    LUNCH_PEAK    = "lunch_peak"     # 12:00–14:00  avg CI ~0.50
    AFTERNOON     = "afternoon"      # 14:00–17:00  avg CI ~0.49
    EVENING_RUSH  = "evening_rush"   # 17:00–19:00  avg CI ~0.72 (peak 19: 0.74)
    EVENING_WIND  = "evening_wind"   # 19:00–20:00  avg CI ~0.24


# ──────────────────────────────────────────────
# RAW DETECTION (from YOLO/OpenCV pipeline)
# ──────────────────────────────────────────────

@dataclass
class YOLODetection:
    """
    Exactly what the existing CCTV detection pipeline delivers per frame.
    Fields map 1:1 to the YOLO tracker output shown in the camera screenshot.
    """
    lane_id: int                         # 1-4 matching polygon zone
    vehicle_ids: list[int]               # ByteTrack / DeepSORT unique IDs
    vehicle_count_now: int               # Current vehicles inside zone
    vehicle_count_total: int             # Cumulative count since reset
    vehicle_types: list[VehicleType]     # Per-detection classification
    fps: float                           # Current processing FPS
    timestamp: float = field(default_factory=time.time)

    # Optional enriched fields (available from later pipeline stages)
    avg_speed_kmh: Optional[float] = None
    queue_length_vehicles: Optional[int] = None


# ──────────────────────────────────────────────
# SMOOTHED LANE STATE (after noise filtering)
# ──────────────────────────────────────────────

@dataclass
class LaneState:
    """
    Noise-filtered, smoothed state for one physical lane.
    Updated every control cycle (1 Hz) from raw YOLO detections.

    The exponential moving average (EMA) prevents rapid signal flickering
    caused by detection jitter on low FPS cameras (~3.3 FPS observed).
    """
    lane_id: int
    direction: Direction
    lane_type: LaneType

    # ── Smoothed measurements (EMA filtered) ──
    vehicle_count: float = 0.0           # EMA-smoothed count
    queue_length: float = 0.0            # EMA-smoothed queue (vehicles)
    occupancy_pct: float = 0.0           # 0.0–1.0 fraction of lane filled
    avg_speed_kmh: float = 0.0           # EMA speed

    # ── Flow accounting ──
    inflow_rate: float = 0.0             # vehicles/cycle entering
    outflow_rate: float = 0.0            # vehicles/cycle leaving
    net_accumulation: float = 0.0        # inflow - outflow (positive = building)

    # ── Timing ──
    cumulative_wait_sec: float = 0.0     # total wait accumulated this red phase
    time_since_last_green: float = 0.0   # seconds since direction last had green

    # ── Signal ──
    current_signal: SignalState = SignalState.RED

    # ── Raw snapshot for logging ──
    raw_count_history: list[int] = field(default_factory=list)  # last N raw counts

    # ── Hysteresis flags ──
    congestion_confirmed: bool = False   # must exceed threshold for N consecutive cycles
    congestion_counter: int = 0

    def update_ema(self, new_value: float, current: float, alpha: float = 0.3) -> float:
        """
        Exponential Moving Average.
        alpha=0.3 → 70% weight on history = stable signal, ~3s lag.
        alpha=0.5 → faster response but noisier.
        Tune alpha based on camera FPS and desired responsiveness.
        """
        return alpha * new_value + (1.0 - alpha) * current

    def ingest_detection(self, detection: YOLODetection, cycle_dt: float):
        """
        Consume one YOLO detection snapshot, apply EMA smoothing.
        Called once per control cycle from the detection adapter.
        """
        # Raw snapshot ring buffer (last 10)
        self.raw_count_history.append(detection.vehicle_count_now)
        if len(self.raw_count_history) > 10:
            self.raw_count_history.pop(0)

        # EMA smoothing
        self.vehicle_count = self.update_ema(detection.vehicle_count_now, self.vehicle_count)

        if detection.queue_length_vehicles is not None:
            self.queue_length = self.update_ema(
                detection.queue_length_vehicles, self.queue_length
            )

        if detection.avg_speed_kmh is not None:
            self.avg_speed_kmh = self.update_ema(detection.avg_speed_kmh, self.avg_speed_kmh)

        # Occupancy derived from queue (assuming max 20 vehicles per lane)
        MAX_LANE_CAPACITY = 20.0
        self.occupancy_pct = min(1.0, self.vehicle_count / MAX_LANE_CAPACITY)

        # Hysteresis for congestion confirmation
        # Must exceed threshold for 3 consecutive cycles to confirm
        CONGESTION_THRESHOLD = 0.75
        if self.occupancy_pct >= CONGESTION_THRESHOLD:
            self.congestion_counter = min(self.congestion_counter + 1, 5)
        else:
            self.congestion_counter = max(self.congestion_counter - 1, 0)

        self.congestion_confirmed = self.congestion_counter >= 3

        # Wait time tracking
        if self.current_signal in (SignalState.RED, SignalState.YELLOW):
            self.cumulative_wait_sec += cycle_dt
            self.time_since_last_green += cycle_dt
        else:
            self.cumulative_wait_sec = 0.0
            self.time_since_last_green = 0.0


# ──────────────────────────────────────────────
# APPROACH ARM (one direction at one intersection)
# ──────────────────────────────────────────────

@dataclass
class ApproachArm:
    """
    One directional approach to an intersection.
    Contains the 2 incoming + 2 outgoing lanes.
    """
    direction: Direction
    intersection_id: int

    # L1 = straight/right, L2 = left-turn
    incoming_l1: LaneState = field(default_factory=lambda: LaneState(
        lane_id=1, direction=Direction.NORTH, lane_type=LaneType.INCOMING_STRAIGHT_RIGHT
    ))
    incoming_l2: LaneState = field(default_factory=lambda: LaneState(
        lane_id=2, direction=Direction.NORTH, lane_type=LaneType.INCOMING_LEFT_TURN
    ))
    # L3, L4 = outgoing
    outgoing_l3: LaneState = field(default_factory=lambda: LaneState(
        lane_id=3, direction=Direction.NORTH, lane_type=LaneType.OUTGOING_PRIMARY
    ))
    outgoing_l4: LaneState = field(default_factory=lambda: LaneState(
        lane_id=4, direction=Direction.NORTH, lane_type=LaneType.OUTGOING_SECONDARY
    ))

    @property
    def outgoing_occupancy(self) -> float:
        """Average occupancy of the two outgoing lanes."""
        return (self.outgoing_l3.occupancy_pct + self.outgoing_l4.occupancy_pct) / 2.0

    @property
    def outgoing_blocked(self) -> bool:
        """
        True if outgoing lanes are too full to accept more vehicles.
        CRITICAL: used to suppress green on the incoming approach feeding into these lanes.
        Threshold: 80% occupancy confirmed for 3 cycles.
        """
        return (
            self.outgoing_l3.congestion_confirmed
            and self.outgoing_l4.congestion_confirmed
        )

    @property
    def total_incoming_queue(self) -> float:
        return self.incoming_l1.queue_length + self.incoming_l2.queue_length

    @property
    def total_incoming_count(self) -> float:
        return self.incoming_l1.vehicle_count + self.incoming_l2.vehicle_count

    @property
    def max_wait_sec(self) -> float:
        return max(
            self.incoming_l1.time_since_last_green,
            self.incoming_l2.time_since_last_green,
        )


# ──────────────────────────────────────────────
# PEDESTRIAN STATE
# ──────────────────────────────────────────────

@dataclass
class PedestrianState:
    """
    Per-crosswalk pedestrian demand tracker.
    Crosswalk ID convention: 'N' = north crosswalk (vehicles cross east-west), etc.
    """
    crosswalk_id: str      # 'N', 'S', 'E', 'W'
    waiting_count: int = 0
    wait_time_sec: float = 0.0
    button_pressed: bool = False        # Push-button demand (future hardware)
    estimated_crossing_time: float = 20.0  # baseline seconds

    # Adaptive crossing time: 4s base + 2s per pedestrian, capped at 45s
    MIN_CROSSING_SEC = 12.0
    MAX_CROSSING_SEC = 45.0
    SEC_PER_PEDESTRIAN = 2.0

    MAX_RED_WAIT_SEC = 90.0   # Hard limit: ped signal CANNOT stay red longer than this

    @property
    def adaptive_crossing_duration(self) -> float:
        """
        Computed pedestrian green duration based on observed demand.
        Returns seconds the pedestrian phase should last.
        """
        if self.waiting_count == 0:
            return self.MIN_CROSSING_SEC

        duration = self.MIN_CROSSING_SEC + self.waiting_count * self.SEC_PER_PEDESTRIAN
        return min(self.MAX_CROSSING_SEC, duration)

    @property
    def priority_score(self) -> float:
        """
        How urgently does this crosswalk need a green?
        Used by the scheduler to insert a ped phase.
        """
        wait_penalty = self.wait_time_sec / self.MAX_RED_WAIT_SEC
        demand_factor = min(1.0, self.waiting_count / 10.0)
        return (0.6 * wait_penalty + 0.4 * demand_factor)

    @property
    def must_serve(self) -> bool:
        """Hard constraint: pedestrian wait exceeded maximum."""
        return self.wait_time_sec >= self.MAX_RED_WAIT_SEC


# ──────────────────────────────────────────────
# PHASE TIMING RECORD
# ──────────────────────────────────────────────

@dataclass
class PhaseTimingRecord:
    """Result of the AI's timing computation for one phase."""
    phase_id: PhaseID
    green_duration_sec: float
    reason: str                          # Human-readable justification
    pressure_score: float                # The score that led to selection
    anti_gridlock_active: bool = False   # Was outgoing suppression applied?
    emergency_override: bool = False


# ──────────────────────────────────────────────
# INTERSECTION SNAPSHOT (sent to frontend/log)
# ──────────────────────────────────────────────

@dataclass
class IntersectionSnapshot:
    """
    Complete state of one intersection at one point in time.
    This is the object serialized to JSON and pushed via WebSocket.
    """
    intersection_id: int
    intersection_name: str
    timestamp: float

    # Signal state per approach
    north_signal: SignalState
    south_signal: SignalState
    east_signal:  SignalState
    west_signal:  SignalState

    # Current phase
    active_phase: PhaseID
    phase_elapsed_sec: float
    phase_remaining_sec: float

    # Metrics
    avg_wait_sec: float
    total_queue: int
    congestion_index: float          # 0.0–1.0, matches dataset field
    throughput_vph: float            # vehicles per hour (rolling 5-min)

    # AI metadata
    ai_mode: bool
    ai_decision_reason: str
    anti_gridlock_active: bool
    pedestrian_waiting: dict[str, int]   # crosswalk_id → waiting_count
    emergency_active: bool

    # Neighbor coordination
    neighbor_pressure: dict[int, float]  # intersection_id → pressure score
