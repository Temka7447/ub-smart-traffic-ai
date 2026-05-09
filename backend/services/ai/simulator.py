"""
Simulator Engine — 9-Intersection City Grid
=============================================
Manages the full 3×3 intersection grid, runs the control tick loop,
and coordinates multi-intersection green wave optimization.
Designed to be driven by FastAPI + WebSocket (see main.py).

Intersection naming from UB dataset:
  IDs 0-8 map to real UB intersections.
  Known names from dataset: Баруун 4 зам (id=1), Төв шуудан (id=2)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict
from typing import Optional

from .lane_state import (
    Direction, IntersectionSnapshot, VehicleType,
    WeatherCondition, YOLODetection,
)
from .ai_controller import (
    IntersectionAIController,
    MultiIntersectionCoordinator,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# INTERSECTION NAMES (from UB dataset + placeholders for 9 total)
# ──────────────────────────────────────────────
INTERSECTION_NAMES = {
    0: "Сүхбаатар талбай",       # Grid [0,0]
    1: "Баруун 4 зам",           # Grid [0,1] — in dataset
    2: "Зайсан уулзвар",         # Grid [0,2]
    3: "Их дэлгүүр",             # Grid [1,0]
    4: "Төв цэвэрлэх байгуулам", # Grid [1,1]
    5: "Төв шуудан",             # Grid [1,2] — in dataset
    6: "Нарны зам уулзвар",      # Grid [2,0]
    7: "Мэдээлэл технологи",     # Grid [2,1]
    8: "Яармаг уулзвар",         # Grid [2,2]
}


class TrafficSimulator:
    """
    Central simulator managing all 9 intersections.

    Responsibilities:
    - Instantiate and own all IntersectionAIController objects
    - Run the main tick() loop at 1 Hz
    - Pipe incoming YOLO detections to the correct intersection/lane
    - Collect snapshots and broadcast via WebSocket
    - Multi-intersection coordination (green wave)
    - Comparison mode: maintains a traditional clone of each intersection
    """

    TICK_RATE_HZ = 1.0   # Control loop: 1 tick per second
    NUM_INTERSECTIONS = 9

    def __init__(self, comparison_mode: bool = True):
        """
        comparison_mode=True: runs both AI and traditional controllers side-by-side.
        This powers the split-screen comparison in the frontend.
        """
        self.comparison_mode = comparison_mode
        self.running = False
        self._tick_count = 0

        # AI controllers
        self.ai_controllers: dict[int, IntersectionAIController] = {
            i: IntersectionAIController(
                intersection_id=i,
                intersection_name=INTERSECTION_NAMES.get(i, f"INT-{i}"),
                ai_mode=True,
            )
            for i in range(self.NUM_INTERSECTIONS)
        }

        # Traditional controllers (mirror of AI, but fixed timing)
        self.traditional_controllers: dict[int, IntersectionAIController] = {}
        if comparison_mode:
            self.traditional_controllers = {
                i: IntersectionAIController(
                    intersection_id=i,
                    intersection_name=INTERSECTION_NAMES.get(i, f"INT-{i}"),
                    ai_mode=False,
                )
                for i in range(self.NUM_INTERSECTIONS)
            }

        # Multi-intersection coordinator
        self.coordinator = MultiIntersectionCoordinator()

        # Latest snapshot cache (for WebSocket broadcasting)
        self._latest_ai_snapshots: dict[int, IntersectionSnapshot] = {}
        self._latest_trad_snapshots: dict[int, IntersectionSnapshot] = {}

        # Global weather state
        self._weather = WeatherCondition.CLEAR

        # Simulation metrics
        self._sim_start_time = time.time()
        self._metrics_history: list[dict] = []

        logger.info(f"TrafficSimulator initialized: {self.NUM_INTERSECTIONS} intersections, "
                    f"comparison_mode={comparison_mode}")

    # ─────────────────────────────────────────
    # MAIN CONTROL LOOP
    # ─────────────────────────────────────────

    async def run_async(self, broadcast_callback=None):
        """
        Async tick loop. Run this as an asyncio background task.
        broadcast_callback: async function(payload: dict) called each tick.
        """
        self.running = True
        tick_interval = 1.0 / self.TICK_RATE_HZ
        logger.info("Simulator tick loop started")

        while self.running:
            tick_start = time.monotonic()
            self._tick_count += 1

            # Run one tick on all controllers
            ai_snapshots = self._tick_all_controllers(
                self.ai_controllers, dt=tick_interval
            )
            trad_snapshots = {}
            if self.comparison_mode:
                trad_snapshots = self._tick_all_controllers(
                    self.traditional_controllers, dt=tick_interval
                )

            self._latest_ai_snapshots = ai_snapshots
            self._latest_trad_snapshots = trad_snapshots

            # Multi-intersection coordination: compute pressure map and propagate
            self._run_coordination(ai_snapshots)

            # Collect aggregate metrics every 5 ticks
            if self._tick_count % 5 == 0:
                self._collect_metrics(ai_snapshots, trad_snapshots)

            # Broadcast via WebSocket if callback provided
            if broadcast_callback is not None:
                payload = self._build_broadcast_payload(ai_snapshots, trad_snapshots)
                await broadcast_callback(payload)

            # Sleep for remainder of tick interval
            elapsed = time.monotonic() - tick_start
            sleep_time = max(0.0, tick_interval - elapsed)
            await asyncio.sleep(sleep_time)

    def _tick_all_controllers(
        self,
        controllers: dict[int, IntersectionAIController],
        dt: float,
    ) -> dict[int, IntersectionSnapshot]:
        snapshots = {}
        for int_id, ctrl in controllers.items():
            try:
                ctrl.tick(dt)
                snapshots[int_id] = ctrl.get_snapshot()
            except Exception as e:
                logger.error(f"Tick error INT-{int_id}: {e}", exc_info=True)
        return snapshots

    def _run_coordination(self, snapshots: dict[int, IntersectionSnapshot]):
        """
        Multi-intersection pressure propagation.
        Adjusts timing at congested intersections based on neighbor state.
        """
        pressure_map = {
            int_id: snap.congestion_index
            for int_id, snap in snapshots.items()
        }
        for int_id, ctrl in self.ai_controllers.items():
            neighbor_factor = self.coordinator.propagate_pressure(
                int_id, pressure_map.get(int_id, 0.0), pressure_map
            )
            # Inject neighbor context into controller (informational, used by timing)
            if int_id in snapshots:
                snapshots[int_id].neighbor_pressure = {
                    nid: pressure_map.get(nid, 0.0)
                    for nid in self.coordinator.get_neighbors(int_id).values()
                    if nid is not None
                }

    # ─────────────────────────────────────────
    # DETECTION INGESTION
    # ─────────────────────────────────────────

    def ingest_camera_detection(
        self,
        intersection_id: int,
        lane_id: int,
        vehicle_count: int,
        vehicle_types: list[str],
        queue_length: Optional[float] = None,
        avg_speed: Optional[float] = None,
        fps: float = 3.3,
    ):
        """
        Called by the YOLO/FastAPI detection endpoint.
        Routes detection to correct intersection controller.
        """
        if intersection_id not in self.ai_controllers:
            logger.warning(f"Unknown intersection_id {intersection_id}")
            return

        vt_map = {
            'car': VehicleType.CAR,
            'bus': VehicleType.BUS,
            'truck': VehicleType.TRUCK,
            'emergency': VehicleType.EMERGENCY,
        }
        vtypes = [vt_map.get(v, VehicleType.CAR) for v in vehicle_types]

        detection = YOLODetection(
            lane_id=lane_id,
            vehicle_ids=[],          # ByteTrack IDs not needed at this layer
            vehicle_count_now=vehicle_count,
            vehicle_count_total=vehicle_count,
            vehicle_types=vtypes,
            fps=fps,
            queue_length_vehicles=int(queue_length) if queue_length else None,
            avg_speed_kmh=avg_speed,
        )

        dt = 1.0 / self.TICK_RATE_HZ
        self.ai_controllers[intersection_id].ingest_detections({lane_id: detection}, dt)
        if self.comparison_mode and intersection_id in self.traditional_controllers:
            self.traditional_controllers[intersection_id].ingest_detections(
                {lane_id: detection}, dt
            )

    def update_weather(self, weather: WeatherCondition):
        """Broadcast weather condition to all controllers."""
        self._weather = weather
        for ctrl in self.ai_controllers.values():
            ctrl.weather = weather
        logger.info(f"Weather updated: {weather.value}")

    # ─────────────────────────────────────────
    # METRICS AND PAYLOAD
    # ─────────────────────────────────────────

    def _collect_metrics(
        self,
        ai_snaps: dict[int, IntersectionSnapshot],
        trad_snaps: dict[int, IntersectionSnapshot],
    ):
        def avg_metric(snaps, attr):
            vals = [getattr(s, attr) for s in snaps.values()]
            return round(sum(vals) / len(vals), 2) if vals else 0.0

        metrics = {
            'timestamp': time.time(),
            'sim_uptime_sec': round(time.time() - self._sim_start_time, 0),
            'ai': {
                'avg_wait_sec': avg_metric(ai_snaps, 'avg_wait_sec'),
                'avg_congestion': avg_metric(ai_snaps, 'congestion_index'),
                'total_queue': sum(s.total_queue for s in ai_snaps.values()),
                'emergency_active': any(s.emergency_active for s in ai_snaps.values()),
            },
            'traditional': {
                'avg_wait_sec': avg_metric(trad_snaps, 'avg_wait_sec'),
                'avg_congestion': avg_metric(trad_snaps, 'congestion_index'),
                'total_queue': sum(s.total_queue for s in trad_snaps.values()),
            } if trad_snaps else {},
        }
        self._metrics_history.append(metrics)
        if len(self._metrics_history) > 1000:   # Keep last 1000 samples
            self._metrics_history.pop(0)

    def _build_broadcast_payload(
        self,
        ai_snaps: dict[int, IntersectionSnapshot],
        trad_snaps: dict[int, IntersectionSnapshot],
    ) -> dict:
        """
        WebSocket broadcast payload.
        Matches the structure expected by IntersectionCanvas.jsx and MetricsPanel.jsx.
        """
        def snap_to_dict(snap: IntersectionSnapshot) -> dict:
            return {
                'id': snap.intersection_id,
                'name': snap.intersection_name,
                'signals': {
                    'N': snap.north_signal.value,
                    'S': snap.south_signal.value,
                    'E': snap.east_signal.value,
                    'W': snap.west_signal.value,
                },
                'phase': snap.active_phase.value,
                'phase_elapsed': snap.phase_elapsed_sec,
                'phase_remaining': snap.phase_remaining_sec,
                'metrics': {
                    'avg_wait': snap.avg_wait_sec,
                    'queue': snap.total_queue,
                    'congestion_index': snap.congestion_index,
                    'throughput_vph': snap.throughput_vph,
                },
                'ai_mode': snap.ai_mode,
                'ai_reason': snap.ai_decision_reason,
                'anti_gridlock': snap.anti_gridlock_active,
                'pedestrian': snap.pedestrian_waiting,
                'emergency': snap.emergency_active,
                'neighbor_pressure': snap.neighbor_pressure,
            }

        latest_metrics = self._metrics_history[-1] if self._metrics_history else {}

        return {
            'type': 'simulation_update',
            'tick': self._tick_count,
            'timestamp': time.time(),
            'intersections': {
                'ai': {i: snap_to_dict(s) for i, s in ai_snaps.items()},
                'traditional': {i: snap_to_dict(s) for i, s in trad_snaps.items()},
            },
            'aggregate': latest_metrics,
            'weather': self._weather.value,
        }

    def get_current_state(self) -> dict:
        """REST endpoint: return current full state synchronously."""
        return self._build_broadcast_payload(
            self._latest_ai_snapshots,
            self._latest_trad_snapshots,
        )

    def stop(self):
        self.running = False
        logger.info("Simulator stopped")
