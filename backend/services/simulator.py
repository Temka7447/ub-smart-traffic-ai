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
from backend.services.ai_controller import calculate_green_time

DIRECTIONS = ("north", "south", "east", "west")
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

        self.is_running = False
        self.speed = 1.0

        self.active_dir = "north"
        self.dir_index = 0
        self.phase_timer = 30

        self.queues = self._create_initial_queues(False, False)
        self.total_passed = 0
        self.wait_times: dict[str, list[int]] = {"fixed": [], "ai": []}
        self.vehicles: list[dict[str, Any]] = []
        self.intersections = self._create_intersections()

        self.sim_time = 0
        self.history: list[dict[str, int]] = []
        self.green_times = {direction: 30 for direction in DIRECTIONS}

        self._frame = 0
        self._vehicle_id = 0

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
            "north": 18 if peak_hour and heavy_north else 12 if peak_hour else 14 if heavy_north else 6,
            "south": 10 if peak_hour else 5,
            "east": 8 if peak_hour else 4,
            "west": 9 if peak_hour else 5,
        }

    def _create_intersections(self) -> list[dict[str, Any]]:
        intersections: list[dict[str, Any]] = []
        for pos in INTERSECTION_POSITIONS:
            intersections.append(
                {
                    **pos,
                    "queues": {
                        "north": self._rng.randint(1, 8),
                        "south": self._rng.randint(1, 8),
                        "east": self._rng.randint(1, 8),
                        "west": self._rng.randint(1, 8),
                    },
                    "activeDir": self._rng.choice(DIRECTIONS),
                    "timer": self._rng.randint(0, 29),
                }
            )
        return intersections

    def _avg_wait(self, waits: list[int]) -> int:
        if not waits:
            return 0
        return int(round(sum(waits) / len(waits)))

    def _refresh_green_times(self) -> None:
        if self.mode == "ai":
            self.green_times = calculate_green_time(
                self.queues,
                is_peak_hour=self.peak_hour,
                bus_directions=self.bus_directions,
            )
        else:
            self.green_times = {direction: 30 for direction in DIRECTIONS}

    def _spawn_vehicle(self, direction: str) -> dict[str, Any]:
        self._vehicle_id += 1
        is_vertical = direction in ("north", "south")
        x = -30 if direction == "east" else 830 if direction == "west" else 380 if direction == "north" else 420
        y = -30 if direction == "south" else 530 if direction == "north" else 250 if is_vertical else 270
        vehicle_types = ["car", "car", "car", "bus", "truck"]
        return {
            "id": self._vehicle_id,
            "dir": direction,
            "type": self._rng.choice(vehicle_types),
            "x": float(x),
            "y": float(y),
            "waiting": False,
            "color": (
                "#ff6d00"
                if direction == "north"
                else "#00e5ff"
                if direction == "south"
                else "#ffd600"
                if direction == "east"
                else "#c653ff"
            ),
        }

    def _reset_runtime_state(self) -> None:
        self.is_running = False
        self.active_dir = "north"
        self.dir_index = 0
        self.phase_timer = 30
        self.queues = self._create_initial_queues(self.peak_hour, self.heavy_north)
        self.total_passed = 0
        self.wait_times = {"fixed": [], "ai": []}
        self.vehicles = []
        self.intersections = self._create_intersections()
        self.sim_time = 0
        self.history = []
        self._frame = 0
        self._vehicle_id = 0
        self._refresh_green_times()

    async def _tick(self) -> SimulationState:
        async with self._lock:
            if not self.is_running:
                return self._snapshot_locked()

            self._frame += 1

            self.phase_timer -= 1
            if self.phase_timer <= 0:
                self.dir_index = (self.dir_index + 1) % len(DIRECTIONS)
                self.active_dir = DIRECTIONS[self.dir_index]

                self._refresh_green_times()
                self.phase_timer = 30 if self.mode == "fixed" else self.green_times[self.active_dir]

            updated_queues = dict(self.queues)
            base_arrival_rate = 0.4 if self.peak_hour else 0.2
            north_arrival_rate = min(0.95, base_arrival_rate + 0.2) if self.heavy_north else base_arrival_rate

            for direction in DIRECTIONS:
                arrival_rate = north_arrival_rate if direction == "north" else base_arrival_rate
                if self._rng.random() < arrival_rate:
                    updated_queues[direction] = min(40, updated_queues[direction] + 1)

            current_dir = DIRECTIONS[self.dir_index]
            if updated_queues[current_dir] > 0:
                discharge = 2 if self.mode == "ai" else 1
                moved = min(discharge, updated_queues[current_dir])
                updated_queues[current_dir] = max(0, updated_queues[current_dir] - moved)
                self.total_passed += moved

                wait_val = 30 - self.phase_timer
                mode_waits = self.wait_times[self.mode]
                self.wait_times[self.mode] = [*mode_waits[-19:], wait_val]

            self.queues = updated_queues

            next_intersections: list[dict[str, Any]] = []
            for inter in self.intersections:
                new_timer = inter["timer"] - 1
                new_active_dir = inter["activeDir"]
                new_queues = dict(inter["queues"])

                for direction in DIRECTIONS:
                    if self._rng.random() < 0.3:
                        new_queues[direction] = min(20, new_queues[direction] + 1)

                if new_queues[new_active_dir] > 0:
                    new_queues[new_active_dir] = max(0, new_queues[new_active_dir] - 1)

                if new_timer <= 0:
                    idx = DIRECTIONS.index(new_active_dir)
                    new_active_dir = DIRECTIONS[(idx + 1) % len(DIRECTIONS)]
                    if self.mode == "fixed":
                        new_timer = 30
                    else:
                        new_timer = max(10, min(60, new_queues[new_active_dir] * 2 + 10))

                next_intersections.append(
                    {
                        **inter,
                        "timer": new_timer,
                        "activeDir": new_active_dir,
                        "queues": new_queues,
                    }
                )

            self.intersections = next_intersections

            if self._frame % 2 == 0:
                spawn_chance = 0.6 if self.peak_hour else 0.3
                if self._rng.random() < spawn_chance and len(self.vehicles) <= 20:
                    if self.heavy_north and self._rng.random() < 0.5:
                        spawn_dir = "north"
                    else:
                        spawn_dir = self._rng.choice(DIRECTIONS)
                    self.vehicles.append(self._spawn_vehicle(spawn_dir))

            moved_vehicles: list[dict[str, Any]] = []
            for vehicle in self.vehicles:
                x = float(vehicle["x"])
                y = float(vehicle["y"])
                direction = vehicle["dir"]
                at_intersection = 340 < x < 460 and 200 < y < 340
                is_green = self.active_dir == direction

                if at_intersection and not is_green:
                    moved_vehicles.append({**vehicle, "waiting": True})
                    continue

                speed_px = 2.5
                if direction == "north":
                    y += speed_px
                elif direction == "south":
                    y -= speed_px
                elif direction == "east":
                    x += speed_px
                else:
                    x -= speed_px

                if -50 < x < 860 and -50 < y < 560:
                    moved_vehicles.append({**vehicle, "x": x, "y": y, "waiting": False})

            self.vehicles = moved_vehicles

            self.sim_time += 1
            total_queue = sum(self.queues.values())
            self.history = [*self.history[-59:], {"t": self.sim_time, "queue": total_queue}]

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
            queues=dict(self.queues),
            totalPassed=self.total_passed,
            waitTimes={
                "fixed": list(self.wait_times["fixed"]),
                "ai": list(self.wait_times["ai"]),
            },
            vehicles=list(self.vehicles),
            intersections=list(self.intersections),
            simTime=self.sim_time,
            history=list(self.history),
            greenTimes=dict(self.green_times),
            avgFixedWait=self._avg_wait(self.wait_times["fixed"]),
            avgAIWait=self._avg_wait(self.wait_times["ai"]),
            busDirections=list(self.bus_directions),
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

            if payload.reset:
                self._reset_runtime_state()

            if payload.autostart:
                self.is_running = True

            self._refresh_green_times()
            if self.mode == "ai":
                self.phase_timer = max(1, min(60, self.phase_timer))

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
            )

    async def get_queue_history(self) -> QueueHistoryResponse:
        async with self._lock:
            return QueueHistoryResponse(history=list(self.history))

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
