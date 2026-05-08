from __future__ import annotations

import asyncio
import random
from contextlib import suppress
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from backend.models.intersection import (
    ComparisonStats,
    QueueHistoryResponse,
    SimulationStartRequest,
    SimulationState,
)
from backend.services.ai_controller import (
    DIRECTIONS,
    LANE_X,
    LANE_Y,
    calculate_green_time,
    get_safe_speed,
    should_yield,
)

CANVAS_WIDTH = 500.0
CANVAS_HEIGHT = 400.0
SPAWN_OFFSET = 40.0
OFF_SCREEN_NORTH = -SPAWN_OFFSET
OFF_SCREEN_SOUTH = CANVAS_HEIGHT + SPAWN_OFFSET
OFF_SCREEN_EAST = -SPAWN_OFFSET
OFF_SCREEN_WEST = CANVAS_WIDTH + SPAWN_OFFSET
EXIT_MARGIN = 80.0

BASE_VEHICLE_SPEED = 2.9
BASE_SPAWN_CHANCE = 0.45
PEAK_SPAWN_CHANCE = 0.78
MAX_ACTIVE_VEHICLES = 56
CENTER_X = CANVAS_WIDTH / 2
CENTER_Y = CANVAS_HEIGHT / 2

INTERSECTION_POSITIONS = [
    {"id": "A", "row": 0, "col": 0, "label": "A"},
    {"id": "B", "row": 0, "col": 1, "label": "B"},
    {"id": "C", "row": 0, "col": 2, "label": "C"},
    {"id": "D", "row": 1, "col": 0, "label": "D"},
    {"id": "E", "row": 1, "col": 1, "label": "E"},
    {"id": "F", "row": 1, "col": 2, "label": "F"},
    {"id": "G", "row": 2, "col": 0, "label": "G"},
    {"id": "H", "row": 2, "col": 1, "label": "H"},
    {"id": "I", "row": 2, "col": 2, "label": "I"},
]

VEHICLE_COLORS: dict[str, str] = {
    "north": "#ff6d00",
    "south": "#00e5ff",
    "east": "#ffd600",
    "west": "#c653ff",
}


class TrafficSimulator:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._subscribers: set[WebSocket] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._rng = random.Random()

        self.mode = "fixed"
        self.peak_hour = False
        self.heavy_north = False
        self.bus_directions: list[str] = []
        self.emergency_directions: list[str] = []

        self.is_running = False
        self.speed = 1.0

        self.active_dir = "north"
        self.dir_index = 0
        self.signal_state = "green"
        self.phase_timer = 30

        self.queues = self._create_initial_queues(False, False)
        self.lane_queues = self._create_initial_lane_queues(self.queues)
        self.total_passed = 0
        self.wait_times: dict[str, list[int]] = {"fixed": [], "ai": []}
        self.vehicles: list[dict[str, Any]] = []
        self.intersections = self._create_intersections()

        self.sim_time = 0
        self.history: list[dict[str, int]] = []
        self.green_times = {direction: 30 for direction in DIRECTIONS}

        self._frame = 0
        self._vehicle_id = 0

    def _create_initial_lane_queues(self, direction_queues: dict[str, int]) -> dict[str, int]:
        lane_queues: dict[str, int] = {}
        for direction in DIRECTIONS:
            total = max(0, direction_queues.get(direction, 0))
            lane_queues[f"{direction}_0"] = total // 2
            lane_queues[f"{direction}_1"] = total - (total // 2)
        return lane_queues

    def _sum_direction_queues(self, lane_queues: dict[str, int]) -> dict[str, int]:
        return {
            direction: lane_queues.get(f"{direction}_0", 0) + lane_queues.get(f"{direction}_1", 0)
            for direction in DIRECTIONS
        }

    def _phase_directions(self, active_dir: str | None = None) -> tuple[str, str]:
        current = active_dir or self.active_dir
        if current in {"north", "south"}:
            return ("north", "south")
        return ("east", "west")

    async def start_loop(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop_loop(self) -> None:
        if self._loop_task is None:
            return
        self._loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._loop_task
        self._loop_task = None

    async def _run_loop(self) -> None:
        while True:
            async with self._lock:
                running = self.is_running
                speed = self.speed

            if not running:
                await asyncio.sleep(0.1)
                continue

            await asyncio.sleep(max(0.01, 1.0 / max(speed, 0.1)))
            state = await self._tick()
            await self._broadcast_state(state)

    def _create_initial_queues(self, peak_hour: bool, heavy_north: bool) -> dict[str, int]:
        return {
            "north": 26 if peak_hour and heavy_north else 17 if peak_hour else 20 if heavy_north else 9,
            "south": 14 if peak_hour else 7,
            "east": 12 if peak_hour else 6,
            "west": 12 if peak_hour else 7,
        }

    def _create_intersections(self) -> list[dict[str, Any]]:
        intersections: list[dict[str, Any]] = []
        for pos in INTERSECTION_POSITIONS:
            direction_queues = {
                "north": self._rng.randint(2, 10),
                "south": self._rng.randint(2, 10),
                "east": self._rng.randint(2, 10),
                "west": self._rng.randint(2, 10),
            }
            lane_queues = self._create_initial_lane_queues(direction_queues)
            intersections.append(
                {
                    **pos,
                    "queues": direction_queues,
                    "laneQueues": lane_queues,
                    "activeDir": self._rng.choice(("north", "east")),
                    "signalState": "green",
                    "timer": self._rng.randint(10, 30),
                    "greenTimes": calculate_green_time(direction_queues),
                }
            )
        return intersections

    def _avg_wait(self, waits: list[int]) -> int:
        if not waits:
            return 0
        return int(round(sum(waits) / len(waits)))

    def _build_vehicle_type_counts(self) -> dict[str, dict[str, int]]:
        type_counts: dict[str, dict[str, int]] = {direction: {} for direction in DIRECTIONS}
        for vehicle in self.vehicles:
            direction = vehicle["dir"]
            vehicle_type = vehicle["type"]
            direction_bucket = type_counts[direction]
            direction_bucket[vehicle_type] = direction_bucket.get(vehicle_type, 0) + 1
        return type_counts

    def _refresh_green_times(self) -> None:
        if self.mode == "ai":
            self.green_times = calculate_green_time(
                self.queues,
                is_peak_hour=self.peak_hour,
                bus_directions=self.bus_directions,
                emergency_directions=self.emergency_directions,
                vehicle_type_counts=self._build_vehicle_type_counts(),
            )
        else:
            self.green_times = {direction: 30 for direction in DIRECTIONS}

    def _spawn_vehicle(self, direction: str) -> dict[str, Any]:
        self._vehicle_id += 1
        turn = self._rng.choices(
            ["straight", "left", "right"],
            weights=[0.55, 0.22, 0.23],
            k=1,
        )[0]
        if turn == "left":
            lane_idx = 0
        elif turn == "right":
            lane_idx = 1
        else:
            lane_idx = self._rng.randint(0, 1)

        if direction == "north":
            x = LANE_X["north"][lane_idx]
            y = OFF_SCREEN_NORTH
        elif direction == "south":
            x = LANE_X["south"][lane_idx]
            y = OFF_SCREEN_SOUTH
        elif direction == "east":
            x = OFF_SCREEN_EAST
            y = LANE_Y["east"][lane_idx]
        else:
            x = OFF_SCREEN_WEST
            y = LANE_Y["west"][lane_idx]

        vehicle_type = self._rng.choice(["car", "car", "car", "bus", "truck"])
        if direction in self.bus_directions and self._rng.random() < 0.4:
            vehicle_type = "bus"

        return {
            "id": self._vehicle_id,
            "dir": direction,
            "type": vehicle_type,
            "lane": lane_idx,
            "turn": turn,
            "x": float(x),
            "y": float(y),
            "waiting": False,
            "color": VEHICLE_COLORS[direction],
        }

    def _is_too_close_to_existing(self, new_vehicle: dict[str, Any]) -> bool:
        min_spawn_dist = 78.0
        new_x = float(new_vehicle["x"])
        new_y = float(new_vehicle["y"])

        for vehicle in self.vehicles:
            if vehicle["dir"] != new_vehicle["dir"] or vehicle.get("lane") != new_vehicle.get("lane"):
                continue

            if new_vehicle["dir"] in {"north", "south"}:
                dist = abs(float(vehicle["y"]) - new_y)
            else:
                dist = abs(float(vehicle["x"]) - new_x)
            if dist < min_spawn_dist:
                return True

        return False

    def _turned_direction(self, current_dir: str, turn: str) -> str:
        if turn == "straight":
            return current_dir
        if current_dir == "north":
            return "east" if turn == "left" else "west"
        if current_dir == "south":
            return "west" if turn == "left" else "east"
        if current_dir == "east":
            return "south" if turn == "left" else "north"
        return "north" if turn == "left" else "south"

    def _can_turn_now(self, vehicle: dict[str, Any]) -> bool:
        direction = vehicle["dir"]
        x = float(vehicle["x"])
        y = float(vehicle["y"])
        if direction == "north":
            return y >= CENTER_Y - 6
        if direction == "south":
            return y <= CENTER_Y + 6
        if direction == "east":
            return x >= CENTER_X - 6
        return x <= CENTER_X + 6

    def _move_vehicle(self, vehicle: dict[str, Any], all_vehicles: list[dict[str, Any]]) -> dict[str, Any] | None:
        direction = vehicle["dir"]
        x = float(vehicle["x"])
        y = float(vehicle["y"])

        can_go = self.signal_state == "green" and direction in self._phase_directions()
        if should_yield(direction, self.active_dir, x, y) and not can_go:
            return {**vehicle, "waiting": True}

        same_lane = [
            other
            for other in all_vehicles
            if other["id"] != vehicle["id"]
            and other["dir"] == direction
            and other.get("lane") == vehicle.get("lane")
        ]
        speed_px = get_safe_speed(vehicle, same_lane, BASE_VEHICLE_SPEED)

        if speed_px == 0.0:
            return {**vehicle, "waiting": True}

        if direction == "north":
            y += speed_px
        elif direction == "south":
            y -= speed_px
        elif direction == "east":
            x += speed_px
        else:
            x -= speed_px

        turn = vehicle.get("turn", "straight")
        if turn != "straight" and self._can_turn_now({**vehicle, "x": x, "y": y}):
            next_dir = self._turned_direction(direction, turn)
            if next_dir in {"north", "south"}:
                x = LANE_X[next_dir][vehicle.get("lane", 0)]
            else:
                y = LANE_Y[next_dir][vehicle.get("lane", 0)]
            direction = next_dir
            turn = "straight"

        if x < (OFF_SCREEN_EAST - EXIT_MARGIN) or x > (OFF_SCREEN_WEST + EXIT_MARGIN):
            return None
        if y < (OFF_SCREEN_NORTH - EXIT_MARGIN) or y > (OFF_SCREEN_SOUTH + EXIT_MARGIN):
            return None

        return {**vehicle, "x": x, "y": y, "dir": direction, "turn": turn, "waiting": False}

    async def _tick(self) -> SimulationState:
        async with self._lock:
            if not self.is_running:
                return self._snapshot_locked()

            self._frame += 1

            self.phase_timer -= 1
            if self.phase_timer <= 0:
                if self.signal_state == "green":
                    self.signal_state = "yellow"
                    self.phase_timer = 3
                elif self.signal_state == "yellow":
                    self.signal_state = "all_red"
                    self.phase_timer = 2
                else:
                    if self.emergency_directions:
                        self.active_dir = "north" if self.emergency_directions[0] in {"north", "south"} else "east"
                    else:
                        self.active_dir = "east" if self.active_dir in {"north", "south"} else "north"
                    self.signal_state = "green"
                    self._refresh_green_times()
                    pair = self._phase_directions()
                    ai_phase = max(self.green_times[pair[0]], self.green_times[pair[1]])
                    self.phase_timer = 30 if self.mode == "fixed" else max(12, min(90, ai_phase))

            updated_queues = dict(self.queues)
            base_arrival_rate = 0.55 if self.peak_hour else 0.30
            north_arrival_rate = min(0.98, base_arrival_rate + 0.20) if self.heavy_north else base_arrival_rate

            for direction in DIRECTIONS:
                arrival_rate = north_arrival_rate if direction == "north" else base_arrival_rate
                if self._rng.random() < arrival_rate:
                    updated_queues[direction] = min(60, updated_queues[direction] + self._rng.randint(1, 2))
                    lane_key = f"{direction}_{self._rng.randint(0, 1)}"
                    self.lane_queues[lane_key] = min(40, self.lane_queues.get(lane_key, 0) + 1)

            if self.signal_state == "green":
                for current_dir in self._phase_directions():
                    if updated_queues[current_dir] <= 0:
                        continue
                    discharge = 3 if self.mode == "ai" else 2
                    if current_dir in self.bus_directions:
                        discharge += 1
                    if current_dir in self.emergency_directions:
                        discharge += 2
                    moved = min(discharge, updated_queues[current_dir])
                    updated_queues[current_dir] = max(0, updated_queues[current_dir] - moved)
                    self.total_passed += moved
                    for lane_idx in (0, 1):
                        lane_key = f"{current_dir}_{lane_idx}"
                        lane_moved = min(moved // 2 + (1 if lane_idx == 0 and moved % 2 else 0), self.lane_queues.get(lane_key, 0))
                        self.lane_queues[lane_key] = max(0, self.lane_queues.get(lane_key, 0) - lane_moved)

                active_cycle = max(self.green_times[d] for d in self._phase_directions()) if self.mode == "ai" else 30
                wait_val = max(1, active_cycle - self.phase_timer)
                mode_waits = self.wait_times[self.mode]
                self.wait_times[self.mode] = [*mode_waits[-39:], wait_val]

            self.queues = updated_queues

            next_intersections: list[dict[str, Any]] = []
            for intersection in self.intersections:
                next_timer = intersection["timer"] - 1
                next_active = intersection["activeDir"]
                next_signal = intersection.get("signalState", "green")
                next_queues = dict(intersection["queues"])
                next_lanes = dict(intersection.get("laneQueues", self._create_initial_lane_queues(next_queues)))

                for direction in DIRECTIONS:
                    if self._rng.random() < 0.35:
                        next_queues[direction] = min(24, next_queues[direction] + 1)
                        lane_key = f"{direction}_{self._rng.randint(0, 1)}"
                        next_lanes[lane_key] = min(20, next_lanes.get(lane_key, 0) + 1)

                if next_signal == "green":
                    phase_pair = self._phase_directions(next_active)
                    for direction in phase_pair:
                        if next_queues[direction] > 0:
                            next_queues[direction] = max(0, next_queues[direction] - 1)

                if next_timer <= 0:
                    if next_signal == "green":
                        next_signal = "yellow"
                        next_timer = 3
                    elif next_signal == "yellow":
                        next_signal = "all_red"
                        next_timer = 2
                    else:
                        next_active = "east" if next_active in {"north", "south"} else "north"
                        next_signal = "green"
                        g_times = calculate_green_time(next_queues)
                        pair = self._phase_directions(next_active)
                        next_timer = 30 if self.mode == "fixed" else max(12, min(90, max(g_times[pair[0]], g_times[pair[1]]) + 4))

                next_intersections.append(
                    {
                        **intersection,
                        "timer": next_timer,
                        "activeDir": next_active,
                        "queues": next_queues,
                        "laneQueues": next_lanes,
                        "signalState": next_signal,
                        "greenTimes": calculate_green_time(next_queues),
                    }
                )

            self.intersections = next_intersections

            spawn_chance = PEAK_SPAWN_CHANCE if self.peak_hour else BASE_SPAWN_CHANCE
            if self._rng.random() < spawn_chance and len(self.vehicles) < MAX_ACTIVE_VEHICLES:
                primary_direction = "north" if self.heavy_north and self._rng.random() < 0.55 else self._rng.choice(DIRECTIONS)
                first_vehicle = self._spawn_vehicle(primary_direction)
                if not self._is_too_close_to_existing(first_vehicle):
                    self.vehicles.append(first_vehicle)

                if self.peak_hour and self._rng.random() < 0.4 and len(self.vehicles) < MAX_ACTIVE_VEHICLES:
                    secondary_direction = self._rng.choice(DIRECTIONS)
                    second_vehicle = self._spawn_vehicle(secondary_direction)
                    if not self._is_too_close_to_existing(second_vehicle):
                        self.vehicles.append(second_vehicle)

            moved_vehicles: list[dict[str, Any]] = []
            for vehicle in self.vehicles:
                moved = self._move_vehicle(vehicle, self.vehicles)
                if moved is not None:
                    moved_vehicles.append(moved)
            self.vehicles = moved_vehicles

            self.sim_time += 1
            total_queue = sum(self.queues.values())
            self.history = [*self.history[-119:], {"t": self.sim_time, "queue": total_queue}]

            self._refresh_green_times()
            return self._snapshot_locked()

    def _snapshot_locked(self) -> SimulationState:
        return SimulationState(
            mode=self.mode,
            peakHour=self.peak_hour,
            heavyNorth=self.heavy_north,
            isRunning=self.is_running,
            speed=round(self.speed, 2),
            activeDir=self.active_dir,
            phaseTimer=self.phase_timer,
            signalState=self.signal_state,
            queues=dict(self.queues),
            laneQueues=dict(self.lane_queues),
            totalPassed=self.total_passed,
            waitTimes={"fixed": list(self.wait_times["fixed"]), "ai": list(self.wait_times["ai"])},
            vehicles=list(self.vehicles),
            intersections=list(self.intersections),
            simTime=self.sim_time,
            history=list(self.history),
            greenTimes=dict(self.green_times),
            avgFixedWait=self._avg_wait(self.wait_times["fixed"]),
            avgAIWait=self._avg_wait(self.wait_times["ai"]),
            busDirections=list(self.bus_directions),
            emergencyDirections=list(self.emergency_directions),
            kpis={
                "avg_wait": float(self._avg_wait(self.wait_times[self.mode])),
                "throughput_per_min": round((self.total_passed / max(1, self.sim_time)) * 60.0, 2),
                "avg_queue_depth": round(sum(self.queues.values()) / max(1, len(self.queues)), 2),
                "queue_stability": float(max(0, 100 - (max(self.queues.values()) - min(self.queues.values())) * 4)),
            },
        )

    async def get_state(self) -> SimulationState:
        async with self._lock:
            return self._snapshot_locked()

    async def start(self, payload: SimulationStartRequest) -> SimulationState:
        async with self._lock:
            if payload.mode is not None:
                self.mode = payload.mode
            if payload.peak_hour is not None:
                self.peak_hour = payload.peak_hour
            if payload.heavy_north is not None:
                self.heavy_north = payload.heavy_north
            if payload.bus_directions is not None:
                self.bus_directions = list(payload.bus_directions)
            if payload.emergency_directions is not None:
                self.emergency_directions = list(payload.emergency_directions)

            if payload.reset:
                self._reset_runtime_state()

            if payload.autostart:
                self.is_running = True

            self._refresh_green_times()
            if self.mode == "ai":
                self.phase_timer = max(1, min(90, self.phase_timer))

            state = self._snapshot_locked()

        await self._broadcast_state(state)
        return state

    async def stop(self) -> SimulationState:
        async with self._lock:
            self.is_running = False
            state = self._snapshot_locked()

        await self._broadcast_state(state)
        return state

    async def set_speed(self, multiplier: float) -> SimulationState:
        async with self._lock:
            self.speed = max(0.5, min(4.0, multiplier))
            state = self._snapshot_locked()

        await self._broadcast_state(state)
        return state

    async def get_comparison_stats(self) -> ComparisonStats:
        async with self._lock:
            fixed_avg = self._avg_wait(self.wait_times["fixed"])
            ai_avg = self._avg_wait(self.wait_times["ai"])
            improvement = 0
            if fixed_avg > 0 and ai_avg > 0:
                improvement = int(round(((fixed_avg - ai_avg) / fixed_avg) * 100))

            return ComparisonStats(
                mode=self.mode,
                avgFixedWait=fixed_avg,
                avgAIWait=ai_avg,
                fixedSamples=len(self.wait_times["fixed"]),
                aiSamples=len(self.wait_times["ai"]),
                improvementPct=improvement,
                totalPassed=self.total_passed,
                throughputPerMinute=round((self.total_passed / max(1, self.sim_time)) * 60.0, 2),
                avgQueueDepth=round(sum(self.queues.values()) / max(1, len(self.queues)), 2),
                queueStability=max(0, 100 - (max(self.queues.values()) - min(self.queues.values())) * 4),
            )

    async def get_queue_history(self) -> QueueHistoryResponse:
        async with self._lock:
            return QueueHistoryResponse(history=list(self.history))

    def _reset_runtime_state(self) -> None:
        self.is_running = False
        self.active_dir = "north"
        self.dir_index = 0
        self.signal_state = "green"
        self.phase_timer = 30
        self.queues = self._create_initial_queues(self.peak_hour, self.heavy_north)
        self.lane_queues = self._create_initial_lane_queues(self.queues)
        self.total_passed = 0
        self.wait_times = {"fixed": [], "ai": []}
        self.vehicles = []
        self.intersections = self._create_intersections()
        self.sim_time = 0
        self.history = []
        self._frame = 0
        self._vehicle_id = 0
        self._refresh_green_times()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._subscribers.add(websocket)
        state = await self.get_state()
        await websocket.send_json(state.model_dump())

    async def disconnect(self, websocket: WebSocket) -> None:
        self._subscribers.discard(websocket)

    async def listen(self, websocket: WebSocket) -> None:
        await self.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await self.disconnect(websocket)

    async def _broadcast_state(self, state: SimulationState | None = None) -> None:
        if not self._subscribers:
            return

        if state is None:
            state = await self.get_state()

        stale: list[WebSocket] = []
        payload = state.model_dump()
        for websocket in list(self._subscribers):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)

        for websocket in stale:
            self._subscribers.discard(websocket)
