from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from backend.services.ai.lane_state import (
    Direction as AIDirection,
    IntersectionSnapshot,
    PhaseID,
    VehicleType,
    YOLODetection,
)
from backend.services.ai.simulator import TrafficSimulator as AIGridSimulator


FRONTEND_DIRECTIONS = ("north", "south", "east", "west")
FIXED_GREEN_TIMES = {direction: 30 for direction in FRONTEND_DIRECTIONS}

MODE_ALIASES = {
    "ai": "ai",
    "fixed": "fixed",
    "traditional": "fixed",
    "normal": "fixed",
}

DIRECTION_TO_AI = {
    "north": AIDirection.NORTH,
    "south": AIDirection.SOUTH,
    "east": AIDirection.EAST,
    "west": AIDirection.WEST,
}

AI_TO_FRONTEND_DIRECTION = {value: key for key, value in DIRECTION_TO_AI.items()}

INCOMING_LANE_IDS = {
    "north": (1, 2),
    "south": (5, 6),
    "east": (9, 10),
    "west": (13, 14),
}

OUTGOING_LANE_IDS = {
    "north": (3, 4),
    "south": (7, 8),
    "east": (11, 12),
    "west": (15, 16),
}

PHASE_TO_ACTIVE_DIR = {
    PhaseID.NS_STRAIGHT: "north",
    PhaseID.NS_LEFT: "north",
    PhaseID.EW_STRAIGHT: "east",
    PhaseID.EW_LEFT: "east",
}

PHASE_TO_GREEN_DIRECTIONS = {
    PhaseID.NS_STRAIGHT: ("north", "south"),
    PhaseID.NS_LEFT: ("north", "south"),
    PhaseID.EW_STRAIGHT: ("east", "west"),
    PhaseID.EW_LEFT: ("east", "west"),
}

VEHICLE_TYPE_MAP = {
    "car": VehicleType.CAR,
    "bus": VehicleType.BUS,
    "truck": VehicleType.TRUCK,
    "emergency": VehicleType.EMERGENCY,
}


def normalize_mode(mode: str) -> str:
    normalized = MODE_ALIASES.get(str(mode).strip().lower())
    if normalized is None:
        allowed = ", ".join(sorted(MODE_ALIASES))
        raise ValueError(f"Unknown mode '{mode}'. Expected one of: {allowed}")
    return normalized


@dataclass
class AIRuntimeState:
    active_dir: str = "north"
    signal_state: str = "green"
    phase_timer: int = 30
    green_times: dict[str, int] = field(default_factory=lambda: dict(FIXED_GREEN_TIMES))
    ai_active_phase: str | None = None
    ai_decision_reason: str = ""
    ai_congestion_state: dict[str, Any] = field(default_factory=dict)
    anti_gridlock_active: bool = False
    pedestrian_waiting: dict[str, int] = field(default_factory=dict)
    emergency_active: bool = False
    neighbor_pressure: dict[str, float] = field(default_factory=dict)
    intersections: list[dict[str, Any]] = field(default_factory=list)


class AIRuntimeManager:
    """
    Bridges the existing React-facing simulator to backend/services/ai.

    The frontend simulator keeps owning vehicle physics and queue animation.
    In AI mode, this manager feeds those live queues into the real AI grid
    simulator, advances IntersectionAIController instances, and returns the
    selected phase/timing metadata for WebSocket snapshots.
    """

    def __init__(self, num_intersections: int = 9) -> None:
        self.num_intersections = num_intersections
        self._core = AIGridSimulator(comparison_mode=False)
        self._green_times = dict(FIXED_GREEN_TIMES)
        self._last_state = AIRuntimeState(green_times=dict(self._green_times))
        self._last_active_dir = "north"
        self._last_decisions: dict[int, Any] = {}
        self._normalise_lane_metadata()
        self.force_decision_next_tick()

    @property
    def green_times(self) -> dict[str, int]:
        return dict(self._green_times)

    @property
    def last_state(self) -> AIRuntimeState:
        return self._last_state

    def reset(self) -> None:
        self._core = AIGridSimulator(comparison_mode=False)
        self._green_times = dict(FIXED_GREEN_TIMES)
        self._last_state = AIRuntimeState(green_times=dict(self._green_times))
        self._last_decisions = {}
        self._normalise_lane_metadata()
        self.force_decision_next_tick()

    def force_decision_next_tick(self) -> None:
        for controller in self._core.ai_controllers.values():
            controller.phase_elapsed_sec = controller.phase_duration_sec

    def tick(
        self,
        *,
        queues: dict[str, int],
        lane_queues: dict[str, int],
        intersections: list[dict[str, Any]],
        vehicles: list[dict[str, Any]],
        bus_directions: list[str],
        emergency_directions: list[str],
        dt: float = 1.0,
    ) -> AIRuntimeState:
        self._sync_controller_inputs(
            intersection_id=0,
            queues=queues,
            lane_queues=lane_queues,
            vehicles=vehicles,
            bus_directions=bus_directions,
            emergency_directions=emergency_directions,
        )

        for index, intersection in enumerate(intersections[: self.num_intersections]):
            if index == 0:
                continue
            self._sync_controller_inputs(
                intersection_id=index,
                queues=intersection.get("queues", {}),
                lane_queues=intersection.get("laneQueues", {}),
                vehicles=[],
                bus_directions=bus_directions,
                emergency_directions=[],
            )

        snapshots: dict[int, IntersectionSnapshot] = {}
        self._last_decisions = {}
        for intersection_id, controller in self._core.ai_controllers.items():
            if intersection_id >= self.num_intersections:
                continue
            controller.ai_mode = True
            decision = controller.tick(dt)
            self._last_decisions[intersection_id] = decision
            snapshots[intersection_id] = controller.get_snapshot()

        self._core._latest_ai_snapshots = snapshots
        self._core._run_coordination(snapshots)

        primary = snapshots.get(0)
        state = self._build_runtime_state(primary, snapshots, intersections)
        self._last_state = state
        return state

    def merge_intersections(self, intersections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self._last_state.intersections:
            return intersections

        by_index = {
            index: metadata
            for index, metadata in enumerate(self._last_state.intersections)
        }
        merged: list[dict[str, Any]] = []
        for index, intersection in enumerate(intersections):
            ai_meta = by_index.get(index)
            if ai_meta is None:
                merged.append(intersection)
                continue
            merged.append({
                **intersection,
                "activeDir": ai_meta["activeDir"],
                "timer": ai_meta["timer"],
                "signalState": ai_meta["signalState"],
                "greenTimes": ai_meta["greenTimes"],
                "activePhase": ai_meta["activePhase"],
                "aiReason": ai_meta["aiReason"],
                "antiGridlock": ai_meta["antiGridlock"],
                "congestionIndex": ai_meta["congestionIndex"],
                "pedestrianWaiting": ai_meta["pedestrianWaiting"],
                "emergencyActive": ai_meta["emergencyActive"],
                "neighborPressure": ai_meta["neighborPressure"],
            })
        return merged

    def _sync_controller_inputs(
        self,
        *,
        intersection_id: int,
        queues: dict[str, int],
        lane_queues: dict[str, int],
        vehicles: list[dict[str, Any]],
        bus_directions: list[str],
        emergency_directions: list[str],
    ) -> None:
        controller = self._core.ai_controllers.get(intersection_id)
        if controller is None:
            return

        for direction, ai_direction in DIRECTION_TO_AI.items():
            total_queue = max(0, int(queues.get(direction, 0)))
            incoming_counts = self._lane_counts(direction, total_queue, lane_queues)
            vehicle_types_by_lane = self._vehicle_types_by_lane(
                direction=direction,
                vehicles=vehicles,
                lane_counts=incoming_counts,
                bus_directions=bus_directions,
                emergency_directions=emergency_directions,
            )

            for lane_offset, lane_id in enumerate(INCOMING_LANE_IDS[direction]):
                count = incoming_counts[lane_offset]
                detection = self._make_detection(
                    lane_id=lane_id,
                    vehicle_count=count,
                    vehicle_types=vehicle_types_by_lane[lane_offset],
                )
                controller.ingest_detections({lane_id: detection}, dt=1.0)

            outgoing_counts = self._outgoing_proxy_counts(direction, queues)
            for lane_offset, lane_id in enumerate(OUTGOING_LANE_IDS[direction]):
                detection = self._make_detection(
                    lane_id=lane_id,
                    vehicle_count=outgoing_counts[lane_offset],
                    vehicle_types=[],
                )
                controller.ingest_detections({lane_id: detection}, dt=1.0)

            if direction in emergency_directions:
                controller.emergency_direction = ai_direction

    def _build_runtime_state(
        self,
        primary: IntersectionSnapshot | None,
        snapshots: dict[int, IntersectionSnapshot],
        existing_intersections: list[dict[str, Any]],
    ) -> AIRuntimeState:
        if primary is None:
            return self._last_state

        active_dir = PHASE_TO_ACTIVE_DIR.get(primary.active_phase, self._last_active_dir)
        self._last_active_dir = active_dir

        signal_state = self._frontend_signal_state(primary.active_phase)
        phase_timer = max(0, int(math.ceil(primary.phase_remaining_sec)))
        self._update_green_times(primary)

        intersections = []
        for index, snapshot in sorted(snapshots.items()):
            base = existing_intersections[index] if index < len(existing_intersections) else {}
            intersections.append(self._snapshot_to_intersection(base, snapshot))

        return AIRuntimeState(
            active_dir=active_dir,
            signal_state=signal_state,
            phase_timer=phase_timer,
            green_times=dict(self._green_times),
            ai_active_phase=primary.active_phase.value,
            ai_decision_reason=primary.ai_decision_reason or self._decision_reason(0),
            ai_congestion_state={
                "index": primary.congestion_index,
                "queue": primary.total_queue,
                "avg_wait_sec": primary.avg_wait_sec,
                "throughput_vph": primary.throughput_vph,
                "state": self._congestion_label(primary.congestion_index),
            },
            anti_gridlock_active=primary.anti_gridlock_active,
            pedestrian_waiting=primary.pedestrian_waiting,
            emergency_active=primary.emergency_active,
            neighbor_pressure={
                str(key): value for key, value in primary.neighbor_pressure.items()
            },
            intersections=intersections,
        )

    def _snapshot_to_intersection(
        self,
        base: dict[str, Any],
        snapshot: IntersectionSnapshot,
    ) -> dict[str, Any]:
        active_dir = PHASE_TO_ACTIVE_DIR.get(snapshot.active_phase, base.get("activeDir", "north"))
        green_times = dict(base.get("greenTimes", FIXED_GREEN_TIMES))
        phase_dirs = PHASE_TO_GREEN_DIRECTIONS.get(snapshot.active_phase, ())
        for direction in phase_dirs:
            green_times[direction] = max(1, int(math.ceil(snapshot.phase_remaining_sec + snapshot.phase_elapsed_sec)))

        return {
            **base,
            "activeDir": active_dir,
            "timer": max(0, int(math.ceil(snapshot.phase_remaining_sec))),
            "signalState": self._frontend_signal_state(snapshot.active_phase),
            "greenTimes": green_times,
            "activePhase": snapshot.active_phase.value,
            "aiReason": snapshot.ai_decision_reason or self._decision_reason(snapshot.intersection_id),
            "antiGridlock": snapshot.anti_gridlock_active,
            "congestionIndex": snapshot.congestion_index,
            "pedestrianWaiting": snapshot.pedestrian_waiting,
            "emergencyActive": snapshot.emergency_active,
            "neighborPressure": {
                str(key): value for key, value in snapshot.neighbor_pressure.items()
            },
        }

    def _update_green_times(self, snapshot: IntersectionSnapshot) -> None:
        phase_dirs = PHASE_TO_GREEN_DIRECTIONS.get(snapshot.active_phase, ())
        if not phase_dirs:
            return
        duration = max(1, int(math.ceil(snapshot.phase_remaining_sec + snapshot.phase_elapsed_sec)))
        for direction in phase_dirs:
            self._green_times[direction] = duration

    def _decision_reason(self, intersection_id: int) -> str:
        decision = self._last_decisions.get(intersection_id)
        return getattr(decision, "reason", "") if decision is not None else ""

    @staticmethod
    def _frontend_signal_state(phase: PhaseID) -> str:
        if phase == PhaseID.ALL_RED or phase in (PhaseID.PEDESTRIAN_NS, PhaseID.PEDESTRIAN_EW):
            return "all_red"
        return "green"

    @staticmethod
    def _lane_counts(
        direction: str,
        total_queue: int,
        lane_queues: dict[str, int],
    ) -> tuple[int, int]:
        lane_0 = lane_queues.get(f"{direction}_0")
        lane_1 = lane_queues.get(f"{direction}_1")
        if lane_0 is None and lane_1 is None:
            lane_0 = total_queue // 2
            lane_1 = total_queue - lane_0
        else:
            lane_0 = int(lane_0 or 0)
            lane_1 = int(lane_1 or 0)
        return max(0, lane_0), max(0, lane_1)

    @staticmethod
    def _outgoing_proxy_counts(
        direction: str,
        queues: dict[str, int],
    ) -> tuple[int, int]:
        # The visual simulator has incoming queues only. Use the receiving arm's
        # current queue as a spillback proxy so the real anti-gridlock guard has
        # a live outgoing occupancy signal to evaluate.
        queue = max(0, int(queues.get(direction, 0)))
        proxy_total = min(40, int(round(queue * 0.8)))
        return proxy_total // 2, proxy_total - (proxy_total // 2)

    @staticmethod
    def _vehicle_types_by_lane(
        *,
        direction: str,
        vehicles: list[dict[str, Any]],
        lane_counts: tuple[int, int],
        bus_directions: list[str],
        emergency_directions: list[str],
    ) -> tuple[list[VehicleType], list[VehicleType]]:
        by_lane = [[], []]
        for vehicle in vehicles:
            if vehicle.get("dir") != direction:
                continue
            lane = int(vehicle.get("lane", 0))
            if lane not in (0, 1):
                lane = 0
            by_lane[lane].append(VEHICLE_TYPE_MAP.get(vehicle.get("type"), VehicleType.CAR))

        if direction in bus_directions:
            for lane in (0, 1):
                if lane_counts[lane] > 0 and VehicleType.BUS not in by_lane[lane]:
                    by_lane[lane].append(VehicleType.BUS)

        if direction in emergency_directions:
            by_lane[0].append(VehicleType.EMERGENCY)

        return by_lane[0], by_lane[1]

    @staticmethod
    def _make_detection(
        *,
        lane_id: int,
        vehicle_count: int,
        vehicle_types: list[VehicleType],
    ) -> YOLODetection:
        return YOLODetection(
            lane_id=lane_id,
            vehicle_ids=[],
            vehicle_count_now=max(0, int(vehicle_count)),
            vehicle_count_total=max(0, int(vehicle_count)),
            vehicle_types=vehicle_types,
            fps=3.3,
            queue_length_vehicles=max(0, int(vehicle_count)),
            avg_speed_kmh=None,
        )

    @staticmethod
    def _congestion_label(index: float) -> str:
        if index >= 0.75:
            return "severe"
        if index >= 0.5:
            return "heavy"
        if index >= 0.25:
            return "moderate"
        return "clear"

    def _normalise_lane_metadata(self) -> None:
        for controller in self._core.ai_controllers.values():
            for direction, arm in controller.arms.items():
                for lane in (
                    arm.incoming_l1,
                    arm.incoming_l2,
                    arm.outgoing_l3,
                    arm.outgoing_l4,
                ):
                    lane.direction = direction
