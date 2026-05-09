# backend/services/simulator.py
from __future__ import annotations

import asyncio
import math
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
from backend.services.ai_runtime_manager import AIRuntimeManager, AIRuntimeState, normalize_mode

# ═══════════════════════════════════════════════════════════
# CANVAS & PHYSICS
# ═══════════════════════════════════════════════════════════
CANVAS_WIDTH        = 500.0
CANVAS_HEIGHT       = 400.0
SPAWN_OFFSET        = 40.0
OFF_SCREEN_NORTH    = -SPAWN_OFFSET
OFF_SCREEN_SOUTH    = CANVAS_HEIGHT + SPAWN_OFFSET
OFF_SCREEN_EAST     = -SPAWN_OFFSET
OFF_SCREEN_WEST     = CANVAS_WIDTH + SPAWN_OFFSET
EXIT_MARGIN         = 80.0
CENTER_X            = CANVAS_WIDTH  / 2
CENTER_Y            = CANVAS_HEIGHT / 2
PHYSICS_HZ          = 12.0
PHYSICS_STEP_SECONDS = 1.0 / PHYSICS_HZ

# ═══════════════════════════════════════════════════════════
# ДАТАСЕТААС ГАРГАСАН ОРГИЛ ЦАГИЙН БОДИТ УТГУУД
# (UB_Traffic_Dataset1.csv — intersection_id=1, hour=8,18)
# ═══════════════════════════════════════════════════════════
# Оргил цагт дундаж queue_length = 18-25, vehicle_count = 15-22
# Тайван цагт дундаж queue_length = 5-10, vehicle_count = 4-8

PEAK_HOURS = {7, 8, 9, 17, 18, 19}   # CSV-ээс авсан

# Тогтмол цикл: cycle_sec=120, green_sec=65 (CSV-д хэзээ ч өөрчлөгддөггүй)
FIXED_CYCLE_SEC     = 120
FIXED_GREEN_SEC     = 30
FIXED_RED_SEC       = 30
FIXED_YELLOW_SEC    = 3

# ═══════════════════════════════════════════════════════════
# ОРГИЛ АЧААЛЛЫН ПАРАМЕТРҮҮД — ДАТАСЕТААС
# ═══════════════════════════════════════════════════════════
# Оргил цагт: arrival_rate өндөр, discharge бага → дараалал хуримтлагдана
# Тогтмол горим: discharge=1 (бодит: 65с ногоон = ~2 машин/цикл)
# AI горим:      discharge=4 (ухаалаг хуваарь → дарааллыг хурдан цэвэрлэнэ)

class PeakLoadConfig:
    """Датасетаас гаргасан оргил цагийн параметрүүд"""
    # Тогтмол горим — яг датасеттэй нийцэж байна
    FIXED_ARRIVAL_RATE   = 0.92   # оргил: 92% магадлалтай машин ирнэ
    FIXED_DISCHARGE      = 1      # 65с ногоон → зөвхөн 1 машин/тик гарна
    FIXED_PHASE_SEC      = 65     # CSV: green_sec=65
    FIXED_MAX_VEHICLES   = 200    # дэлгэцэд 200 хүртэл машин
    FIXED_SPAWN_CHANCE   = 0.97   # маш өндөр spawn магадлал

    # AI горим — зохицуулалтаар дараалал буурна
    AI_ARRIVAL_RATE      = 0.92   # ижил arrival (шударга харьцуулалт)
    AI_DISCHARGE         = 4      # AI: 4 машин/тик — дарааллыг хурдан цэвэрлэнэ
    AI_MAX_VEHICLES      = 200
    AI_SPAWN_CHANCE      = 0.97

    # Тайван цагийн параметрүүд
    NORMAL_ARRIVAL_RATE  = 0.30
    NORMAL_DISCHARGE     = 2
    NORMAL_MAX_VEHICLES  = 56
    NORMAL_SPAWN_CHANCE  = 0.45

    # Оргил цагийн анхны дараалал (CSV queue_length дундаж × 1.5)
    PEAK_INITIAL_QUEUES = {
        "north": 35,   # CSV: avg 23 × 1.5
        "south": 30,
        "east":  28,
        "west":  32,
    }
    NORMAL_INITIAL_QUEUES = {
        "north": 6,
        "south": 5,
        "east":  4,
        "west":  5,
    }

    # Орох/гарах тэнцвэргүй байдал (CSV: inflow > outflow оргил цагт)
    PEAK_INFLOW_BIAS = 2.5    # оргил цагт орох нь гарахаасаа 2.5 дахин их


# ═══════════════════════════════════════════════════════════
DIRECTION_ANGLE = {
    "north": math.pi,
    "east":  math.pi / 2,
    "south": 0.0,
    "west":  -math.pi / 2,
}
DIRECTION_VECTOR = {
    "north": (0.0,  1.0),
    "south": (0.0, -1.0),
    "east":  (1.0,  0.0),
    "west":  (-1.0, 0.0),
}
VEHICLE_DYNAMICS = {
    "car":       {"cruise": 42.0, "accel": 58.0,  "brake": 92.0},
    "truck":     {"cruise": 32.0, "accel": 38.0,  "brake": 70.0},
    "bus":       {"cruise": 30.0, "accel": 34.0,  "brake": 64.0},
    "emergency": {"cruise": 48.0, "accel": 70.0,  "brake": 100.0},
}
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
    "east":  "#ffd600",
    "west":  "#c653ff",
}


class TrafficSimulator:
    def __init__(self) -> None:
        self._lock        = asyncio.Lock()
        self._subscribers: set[WebSocket] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._rng         = random.Random()

        self.mode         = "fixed"
        self.peak_hour    = False
        self.heavy_north  = False
        self.bus_directions:       list[str] = []
        self.emergency_directions: list[str] = []

        self.is_running   = False
        self.speed        = 1.0

        self.active_dir   = "north"
        self.signal_state = "green"
        self.phase_timer  = FIXED_GREEN_SEC   # тогтмол: 65с

        # ── Датасетаас авсан анхны дараалал ──
        self.queues       = dict(PeakLoadConfig.NORMAL_INITIAL_QUEUES)
        self.lane_queues  = self._create_initial_lane_queues(self.queues)

        self.total_passed = 0
        self.wait_times: dict[str, list[int]] = {"fixed": [], "ai": []}
        self.vehicles: list[dict[str, Any]]   = []
        self.intersections = self._create_intersections()

        self.sim_time     = 0
        self.history: list[dict[str, int]] = []
        self.green_times  = {d: FIXED_GREEN_SEC for d in DIRECTIONS}

        self._frame       = 0
        self._vehicle_id  = 0
        self._second_accumulator = 0.0

        # ── Динамик параметрүүд (датасет эсвэл горимоос тохируулагдана) ──
        self._arrival_rate   = PeakLoadConfig.NORMAL_ARRIVAL_RATE
        self._discharge_rate = PeakLoadConfig.NORMAL_DISCHARGE
        self._max_vehicles   = PeakLoadConfig.NORMAL_MAX_VEHICLES
        self._spawn_chance   = PeakLoadConfig.NORMAL_SPAWN_CHANCE
        self._weather_speed_factor = 1.0
        self.ai_runtime = AIRuntimeManager(num_intersections=len(INTERSECTION_POSITIONS))
        self._ai_state = AIRuntimeState()

        # ── KPI хянах ──
        self._queue_snapshots: list[dict[str, int]] = []   # дарааллын хандлага

    # ═══════════════════════════════════════════════════════
    # ГОРИМ ТОХИРУУЛАХ — датасетийн параметр шингэлнэ
    # ═══════════════════════════════════════════════════════
    def _apply_mode_params(self) -> None:
        """
        Горим болон оргил цагаас хамааран динамик параметрүүдийг тохируулна.
        Датасетийн бодит утгуудыг үндэслэсэн.
        """
        if self.peak_hour:
            if self.mode == "fixed":
                # ТОГТМОЛ + ОРГИЛ = ХАМГИЙН ИХ ТҮГЖРЭЛ
                self._arrival_rate   = PeakLoadConfig.FIXED_ARRIVAL_RATE
                self._discharge_rate = PeakLoadConfig.FIXED_DISCHARGE
                self._max_vehicles   = PeakLoadConfig.FIXED_MAX_VEHICLES
                self._spawn_chance   = PeakLoadConfig.FIXED_SPAWN_CHANCE
            else:
                # AI + ОРГИЛ = ЗОХИЦУУЛАЛТ
                self._arrival_rate   = PeakLoadConfig.AI_ARRIVAL_RATE
                self._discharge_rate = PeakLoadConfig.AI_DISCHARGE
                self._max_vehicles   = PeakLoadConfig.AI_MAX_VEHICLES
                self._spawn_chance   = PeakLoadConfig.AI_SPAWN_CHANCE
        else:
            self._arrival_rate   = PeakLoadConfig.NORMAL_ARRIVAL_RATE
            self._discharge_rate = PeakLoadConfig.NORMAL_DISCHARGE
            self._max_vehicles   = PeakLoadConfig.NORMAL_MAX_VEHICLES
            self._spawn_chance   = PeakLoadConfig.NORMAL_SPAWN_CHANCE

    def _apply_dataset_config(self, config: dict[str, Any]) -> None:
        """
        dataset router /load-to-simulator дуудсан үед
        датасетийн бодит утгуудыг симуляторт шингэлнэ.
        """
        if config.get("initial_queues"):
            self.queues      = dict(config["initial_queues"])
            self.lane_queues = self._create_initial_lane_queues(self.queues)

        if config.get("green_times"):
            self.green_times = dict(config["green_times"])

        if config.get("peak_hour") is not None:
            self.peak_hour = bool(config["peak_hour"])

        if config.get("bus_directions"):
            self.bus_directions = list(config["bus_directions"])

        if config.get("weather_factor"):
            self._weather_speed_factor = float(config["weather_factor"])

        # Оргил ачааллын нэмэлт параметрүүд
        if config.get("arrival_rate"):
            self._arrival_rate = float(config["arrival_rate"])
        if config.get("spawn_chance"):
            self._spawn_chance = float(config["spawn_chance"])
        if config.get("max_vehicles"):
            self._max_vehicles = int(config["max_vehicles"])
        if config.get("discharge_rate"):
            self._discharge_rate = int(config["discharge_rate"])

        self._apply_mode_params()

    # ═══════════════════════════════════════════════════════
    # LOOP
    # ═══════════════════════════════════════════════════════
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
                speed   = self.speed
            if not running:
                await asyncio.sleep(0.1)
                continue
            await asyncio.sleep(max(0.01, PHYSICS_STEP_SECONDS / max(speed, 0.1)))
            state = await self._tick(PHYSICS_STEP_SECONDS)
            await self._broadcast_state(state)

    # ═══════════════════════════════════════════════════════
    # АНХНЫ ҮҮСГЭХ
    # ═══════════════════════════════════════════════════════
    def _create_initial_lane_queues(self, direction_queues: dict[str, int]) -> dict[str, int]:
        lane_queues: dict[str, int] = {}
        for direction in DIRECTIONS:
            total = max(0, direction_queues.get(direction, 0))
            lane_queues[f"{direction}_0"] = total // 2
            lane_queues[f"{direction}_1"] = total - (total // 2)
        return lane_queues

    def _phase_directions(self, active_dir: str | None = None) -> tuple[str, str]:
        current = active_dir or self.active_dir
        return ("north", "south") if current in {"north", "south"} else ("east", "west")

    def _create_intersections(self) -> list[dict[str, Any]]:
        intersections: list[dict[str, Any]] = []
        for pos in INTERSECTION_POSITIONS:
            # Оргил цагт дарааллыг датасетийн дундаж утгаар эхлүүлнэ
            if self.peak_hour:
                dq = {d: self._rng.randint(15, 30) for d in DIRECTIONS}
            else:
                dq = {d: self._rng.randint(2, 10) for d in DIRECTIONS}
            lane_queues = self._create_initial_lane_queues(dq)
            intersections.append({
                **pos,
                "queues":      dq,
                "laneQueues":  lane_queues,
                "activeDir":   self._rng.choice(("north", "east")),
                "signalState": "green",
                "timer":       self._rng.randint(10, FIXED_GREEN_SEC),
                "greenTimes":  calculate_green_time(dq),
            })
        return intersections

    def _avg_wait(self, waits: list[int]) -> int:
        return int(round(sum(waits) / len(waits))) if waits else 0

    def _build_vehicle_type_counts(self) -> dict[str, dict[str, int]]:
        type_counts: dict[str, dict[str, int]] = {d: {} for d in DIRECTIONS}
        for v in self.vehicles:
            d  = v["dir"]
            vt = v["type"]
            type_counts[d][vt] = type_counts[d].get(vt, 0) + 1
        return type_counts

    def _refresh_green_times(self) -> None:
        if self.mode == "ai":
            self.green_times = self.ai_runtime.green_times
        else:
            # Тогтмол: CSV-ийн green_sec=65 — хэзээ ч өөрчлөгддөггүй
            self.green_times = {d: FIXED_GREEN_SEC for d in DIRECTIONS}

    def _set_mode_locked(self, mode: str) -> None:
        next_mode = normalize_mode(mode)
        if next_mode == self.mode:
            return

        self.mode = next_mode
        if self.mode == "ai":
            self.ai_runtime.reset()
            self.ai_runtime.force_decision_next_tick()
            self._apply_ai_runtime_state_locked()
        else:
            self.signal_state = "green"
            self.phase_timer = FIXED_GREEN_SEC
            self._ai_state = AIRuntimeState()

        self._apply_mode_params()
        self._refresh_green_times()

    def _apply_ai_runtime_state_locked(self) -> None:
        self._ai_state = self.ai_runtime.tick(
            queues=self.queues,
            lane_queues=self.lane_queues,
            intersections=self.intersections,
            vehicles=self.vehicles,
            bus_directions=self.bus_directions,
            emergency_directions=self.emergency_directions,
            dt=1.0,
        )
        self.active_dir = self._ai_state.active_dir
        self.signal_state = self._ai_state.signal_state
        self.phase_timer = self._ai_state.phase_timer
        self.green_times = dict(self._ai_state.green_times)

    # ═══════════════════════════════════════════════════════
    # МАШИН ҮҮСГЭХ
    # ═══════════════════════════════════════════════════════
    def _spawn_vehicle(self, direction: str) -> dict[str, Any]:
        self._vehicle_id += 1
        turn = self._rng.choices(
            ["straight", "left", "right"],
            weights=[0.55, 0.22, 0.23], k=1
        )[0]
        lane_idx = 0 if turn == "left" else (1 if turn == "right" else self._rng.randint(0, 1))

        if direction == "north":
            x, y = LANE_X["north"][lane_idx], OFF_SCREEN_NORTH
        elif direction == "south":
            x, y = LANE_X["south"][lane_idx], OFF_SCREEN_SOUTH
        elif direction == "east":
            x, y = OFF_SCREEN_EAST, LANE_Y["east"][lane_idx]
        else:
            x, y = OFF_SCREEN_WEST, LANE_Y["west"][lane_idx]

        # Оргил цагт автобус, том машин их байна (CSV-тэй нийцүүлэв)
        if self.peak_hour:
            vehicle_type = self._rng.choices(
                ["car", "bus", "truck"],
                weights=[0.65, 0.22, 0.13], k=1
            )[0]
        else:
            vehicle_type = self._rng.choices(
                ["car", "bus", "truck"],
                weights=[0.80, 0.12, 0.08], k=1
            )[0]

        if direction in self.bus_directions and self._rng.random() < 0.5:
            vehicle_type = "bus"

        return {
            "id":           self._vehicle_id,
            "dir":          direction,
            "type":         vehicle_type,
            "lane":         lane_idx,
            "turn":         turn,
            "x":            float(x),
            "y":            float(y),
            "speed":        0.0,
            "targetSpeed":  VEHICLE_DYNAMICS[vehicle_type]["cruise"] * self._weather_speed_factor,
            "angle":        DIRECTION_ANGLE[direction],
            "steer":        0.0,
            "suspension":   self._rng.uniform(-0.15, 0.15),
            "turnProgress": 0.0,
            "turnStartX":   None,
            "turnStartY":   None,
            "turnEndX":     None,
            "turnEndY":     None,
            "turnFromDir":  None,
            "turnToDir":    None,
            "waiting":      False,
            "color":        VEHICLE_COLORS[direction],
        }

    def _is_too_close_to_existing(self, new_vehicle: dict[str, Any]) -> bool:
        # Оргил цагт зай бага → нягт дараалал
        min_dist = 52.0 if self.peak_hour else 96.0
        new_x = float(new_vehicle["x"])
        new_y = float(new_vehicle["y"])
        for v in self.vehicles:
            if v["dir"] != new_vehicle["dir"] or v.get("lane") != new_vehicle.get("lane"):
                continue
            dist = (
                abs(float(v["y"]) - new_y)
                if new_vehicle["dir"] in {"north", "south"}
                else abs(float(v["x"]) - new_x)
            )
            if dist < min_dist:
                return True
        return False

    # ═══════════════════════════════════════════════════════
    # ХӨДӨЛГӨӨН
    # ═══════════════════════════════════════════════════════
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
        d, x, y = vehicle["dir"], float(vehicle["x"]), float(vehicle["y"])
        if d == "north": return y >= CENTER_Y - 6
        if d == "south": return y <= CENTER_Y + 6
        if d == "east":  return x >= CENTER_X - 6
        return x <= CENTER_X + 6

    def _stop_distance(self, direction: str, x: float, y: float) -> float:
        if direction == "north":
            return 100.0 - y
        if direction == "south":
         return y - 300.0
        if direction == "east":
            return 150.0 - x
        return x - 350.0

    def _angle_lerp(self, current: float, target: float, ratio: float) -> float:
        delta = (target - current + math.pi) % (math.pi * 2) - math.pi
        return current + delta * max(0.0, min(1.0, ratio))

    def _turn_endpoint(self, next_dir: str, lane: int) -> tuple[float, float]:
        if next_dir in {"north", "south"}:
            return LANE_X[next_dir][lane], CENTER_Y + (42.0 if next_dir == "north" else -42.0)
        return CENTER_X + (42.0 if next_dir == "east" else -42.0), LANE_Y[next_dir][lane]

    def _advance_turn(self, vehicle: dict[str, Any], travel_px: float) -> dict[str, Any]:
        sx  = float(vehicle.get("turnStartX") or vehicle["x"])
        sy  = float(vehicle.get("turnStartY") or vehicle["y"])
        ex  = float(vehicle.get("turnEndX")   or vehicle["x"])
        ey  = float(vehicle.get("turnEndY")   or vehicle["y"])
        fd  = vehicle.get("turnFromDir") or vehicle["dir"]
        td  = vehicle.get("turnToDir")   or vehicle["dir"]
        prg = min(1.0, float(vehicle.get("turnProgress", 0.0)) + max(0.018, travel_px / 42.0))
        e   = prg * prg * (3.0 - 2.0 * prg)
        x   = (1-e)**2 * sx + 2*(1-e)*e * CENTER_X + e**2 * ex
        y   = (1-e)**2 * sy + 2*(1-e)*e * CENTER_Y + e**2 * ey
        ang = self._angle_lerp(DIRECTION_ANGLE[fd], DIRECTION_ANGLE[td], e)
        sgn = 1.0 if (DIRECTION_ANGLE[td] - DIRECTION_ANGLE[fd]) > 0 else -1.0
        upd = {
            **vehicle,
            "x": x, "y": y, "angle": ang,
            "steer":      math.sin(prg * math.pi) * 0.18 * sgn,
            "suspension": math.sin((self._frame + vehicle["id"]) * 0.22) * min(1.0, float(vehicle.get("speed", 0.0)) / 44.0),
            "turnProgress": prg,
            "waiting": False,
        }
        if prg >= 1.0:
            upd.update({
                "dir": td, "turn": "straight",
                "angle": DIRECTION_ANGLE[td], "steer": 0.0,
                "turnProgress": 0.0,
                "turnStartX": None, "turnStartY": None,
                "turnEndX":   None, "turnEndY":   None,
                "turnFromDir": None, "turnToDir": None,
            })
        return upd

    def _move_vehicle(
        self,
        vehicle: dict[str, Any],
        all_vehicles: list[dict[str, Any]],
        dt: float = 1.0,
    ) -> dict[str, Any] | None:
        direction   = vehicle["dir"]
        x           = float(vehicle["x"])
        y           = float(vehicle["y"])
        can_go      = self.signal_state == "green" and direction in self._phase_directions()
        same_lane   = [
            o for o in all_vehicles
            if o["id"] != vehicle["id"]
            and o["dir"] == direction
            and o.get("lane") == vehicle.get("lane")
        ]
        dynamics     = VEHICLE_DYNAMICS.get(vehicle.get("type", "car"), VEHICLE_DYNAMICS["car"])
        current_spd  = float(vehicle.get("speed", 0.0))

        # Аюулгүй зай — цаг агаарын нөлөөтэй
        safe_fraction = get_safe_speed(vehicle, same_lane, 1.0)
        target_speed  = dynamics["cruise"] * safe_fraction * self._weather_speed_factor

        stop_dist  = self._stop_distance(direction, x, y)
        must_yield = should_yield(direction, self.active_dir, x, y) and not can_go
        if must_yield and stop_dist > -8.0:
            br = max(0.0, min(1.0, (stop_dist - 4.0) / 58.0))
            target_speed = min(target_speed, dynamics["cruise"] * br * br)

        turn = vehicle.get("turn", "straight")
        if turn != "straight" and vehicle.get("turnProgress", 0.0) <= 0:
            ta = max(0.0, min(1.0, abs(stop_dist) / 95.0))
            if ta < 1.0:
                target_speed = min(target_speed, dynamics["cruise"] * (0.48 + ta * 0.42))

        sd = target_speed - current_spd
        speed_px = current_spd + (
            min(sd,  dynamics["accel"] * dt) if sd >= 0
            else max(sd, -dynamics["brake"] * dt)
        )
        speed_px  = max(0.0, speed_px)
        travel_px = speed_px * dt

        if vehicle.get("turnProgress", 0.0) > 0:
            mv = self._advance_turn({**vehicle, "speed": speed_px, "targetSpeed": target_speed}, travel_px)
            xn, yn = float(mv["x"]), float(mv["y"])
            if xn < (OFF_SCREEN_EAST - EXIT_MARGIN) or xn > (OFF_SCREEN_WEST + EXIT_MARGIN): return None
            if yn < (OFF_SCREEN_NORTH - EXIT_MARGIN) or yn > (OFF_SCREEN_SOUTH + EXIT_MARGIN): return None
            return mv

        if speed_px < 0.04:
            return {
                **vehicle,
                "speed": 0.0, "targetSpeed": target_speed,
                "angle": self._angle_lerp(float(vehicle.get("angle", DIRECTION_ANGLE[direction])), DIRECTION_ANGLE[direction], 0.35),
                "steer": 0.0, "suspension": 0.0,
                "waiting": must_yield or safe_fraction < 0.05,
            }

        dx, dy = DIRECTION_VECTOR[direction]
        x += dx * travel_px
        y += dy * travel_px

        if turn != "straight" and self._can_turn_now({**vehicle, "x": x, "y": y}):
            nd = self._turned_direction(direction, turn)
            ex2, ey2 = self._turn_endpoint(nd, vehicle.get("lane", 0))
            return self._advance_turn({
                **vehicle, "x": x, "y": y, "speed": speed_px, "targetSpeed": target_speed,
                "turnProgress": 0.01,
                "turnStartX": x, "turnStartY": y, "turnEndX": ex2, "turnEndY": ey2,
                "turnFromDir": direction, "turnToDir": nd,
            }, travel_px)

        if x < (OFF_SCREEN_EAST - EXIT_MARGIN) or x > (OFF_SCREEN_WEST + EXIT_MARGIN): return None
        if y < (OFF_SCREEN_NORTH - EXIT_MARGIN) or y > (OFF_SCREEN_SOUTH + EXIT_MARGIN): return None

        return {
            **vehicle, "x": x, "y": y, "dir": direction, "turn": turn,
            "speed": speed_px, "targetSpeed": target_speed,
            "angle": self._angle_lerp(float(vehicle.get("angle", DIRECTION_ANGLE[direction])), DIRECTION_ANGLE[direction], 0.3),
            "steer": 0.0,
            "suspension": math.sin((self._frame + vehicle["id"]) * 0.22) * min(1.0, speed_px / 44.0),
            "waiting": False,
        }

    # ═══════════════════════════════════════════════════════
    # TICK — гол симуляцийн цикл
    # ═══════════════════════════════════════════════════════
    async def _tick(self, dt: float = 1.0) -> SimulationState:
        async with self._lock:
            if not self.is_running:
                return self._snapshot_locked()

            self._frame += 1
            self._second_accumulator += dt
            elapsed_seconds = int(self._second_accumulator)
            if elapsed_seconds:
                self._second_accumulator -= elapsed_seconds

            for _ in range(elapsed_seconds):
                # ── Дохионы фаз ──────────────────────────────────────
                if self.mode == "ai":
                    self._apply_ai_runtime_state_locked()
                else:
                    self.phase_timer -= 1
                    if self.phase_timer <= 0:
                        if self.signal_state == "green":
                            self.signal_state = "yellow"
                            self.phase_timer  = FIXED_YELLOW_SEC
                        elif self.signal_state == "yellow":
                            self.signal_state = "all_red"
                            self.phase_timer  = 2
                        else:
                            # Чиглэл солих
                            if self.emergency_directions:
                                self.active_dir = "north" if self.emergency_directions[0] in {"north", "south"} else "east"
                            else:
                                self.active_dir = "east" if self.active_dir in {"north", "south"} else "north"
                            self.signal_state = "green"
                            self._refresh_green_times()
                            self.phase_timer = FIXED_GREEN_SEC

                # ── Дараалал нэмэх — ОРГИЛ ЦАГТ МАШ ХУРДАН НЭМЭГДЭНЭ ──
                updated_queues = dict(self.queues)

                for direction in DIRECTIONS:
                    # Датасет: arrival_rate оргил цагт 0.92
                    if self._rng.random() < self._arrival_rate:
                        # Оргил цагт нэг удаад 1-3 машин ирнэ
                        add = self._rng.randint(2, 4) if self.peak_hour else self._rng.randint(1, 2)

                        # ТОГТМОЛ горим: дарааллын дээд хязгаарыг 200 болгоно
                        # AI горим: зохицуулснаар хурдан цэвэрлэгдэнэ
                        cap = 200 if self.mode == "fixed" else 120
                        updated_queues[direction] = min(cap, updated_queues[direction] + add)

                        lane_key = f"{direction}_{self._rng.randint(0, 1)}"
                        lane_cap = 100 if self.mode == "fixed" else 60
                        self.lane_queues[lane_key] = min(lane_cap, self.lane_queues.get(lane_key, 0) + add)

                # ── Дараалал цэвэрлэх ───────────────────────────────
                if self.signal_state == "green":
                    for current_dir in self._phase_directions():
                        if updated_queues[current_dir] <= 0:
                            continue

                        # ТОГТМОЛ: discharge=1 → дараалал удаан цэвэрлэгдэнэ
                        # AI:      discharge=4 → 4 дахин хурдан цэвэрлэгдэнэ
                        discharge = self._discharge_rate
                        if current_dir in self.bus_directions:
                            discharge += 1
                        if current_dir in self.emergency_directions:
                            discharge += 3

                        moved = min(discharge, updated_queues[current_dir])
                        updated_queues[current_dir] = max(0, updated_queues[current_dir] - moved)
                        self.total_passed += moved

                        for lane_idx in (0, 1):
                            lane_key  = f"{current_dir}_{lane_idx}"
                            lane_moved = min(
                                moved // 2 + (1 if lane_idx == 0 and moved % 2 else 0),
                                self.lane_queues.get(lane_key, 0),
                            )
                            self.lane_queues[lane_key] = max(0, self.lane_queues.get(lane_key, 0) - lane_moved)

                    # Хүлээлтийн хугацаа тооцох
                    if self.mode == "fixed":
                        wait_val = FIXED_GREEN_SEC - self.phase_timer + FIXED_RED_SEC
                    else:
                        active_cycle = max(self.green_times[d] for d in self._phase_directions())
                        wait_val = max(1, active_cycle - self.phase_timer)
                    self.wait_times[self.mode] = [*self.wait_times[self.mode][-39:], wait_val]

                self.queues = updated_queues

                # ── Хажуугийн уулзварууд ───────────────────────────
                next_intersections: list[dict[str, Any]] = []
                for inter in self.intersections:
                    nt  = inter["timer"] - 1
                    na  = inter["activeDir"]
                    ns  = inter.get("signalState", "green")
                    nq  = dict(inter["queues"])
                    nl  = dict(inter.get("laneQueues", self._create_initial_lane_queues(nq)))

                    for direction in DIRECTIONS:
                        # Оргил цагт хажуугийн уулзварт ч дараалал ихтэй
                        arr = 0.70 if self.peak_hour else 0.35
                        if self._rng.random() < arr:
                            add = self._rng.randint(1, 3) if self.peak_hour else 1
                            nq[direction] = min(80 if self.mode == "fixed" else 40, nq[direction] + add)
                            lk = f"{direction}_{self._rng.randint(0, 1)}"
                            nl[lk] = min(40, nl.get(lk, 0) + add)

                    if ns == "green":
                        for direction in self._phase_directions(na):
                            if nq[direction] > 0:
                                discharge = self._discharge_rate
                                nq[direction] = max(0, nq[direction] - discharge)

                    if nt <= 0:
                        if ns == "green":
                            ns, nt = "yellow", FIXED_YELLOW_SEC
                        elif ns == "yellow":
                            ns, nt = "all_red", 2
                        else:
                            na = "east" if na in {"north", "south"} else "north"
                            ns = "green"
                            gt   = calculate_green_time(nq)
                            pair = self._phase_directions(na)
                            nt = FIXED_GREEN_SEC if self.mode == "fixed" else max(12, min(90, max(gt[pair[0]], gt[pair[1]]) + 4))

                    next_intersections.append({
                        **inter,
                        "timer": nt, "activeDir": na,
                        "queues": nq, "laneQueues": nl,
                        "signalState": ns,
                        "greenTimes": calculate_green_time(nq),
                    })
                self.intersections = (
                    self.ai_runtime.merge_intersections(next_intersections)
                    if self.mode == "ai"
                    else next_intersections
                )

                self.sim_time += 1
                total_q = sum(self.queues.values())
                self.history = [*self.history[-119:], {"t": self.sim_time, "queue": total_q}]

                # KPI snapshot
                self._queue_snapshots = [
                    *self._queue_snapshots[-299:],
                    {**self.queues, "total": total_q, "mode": self.mode},
                ]

            # ── Машин spawn — оргил цагт маш олон ──────────────────
            for _ in range(3 if self.peak_hour else 1):
                if self._rng.random() < self._spawn_chance * dt and len(self.vehicles) < self._max_vehicles:
                    # Оргил цагт хойд чиглэл илүү дүүрэнг датасетаас харлаа
                    weights = [0.35, 0.25, 0.20, 0.20] if self.heavy_north else [0.25, 0.25, 0.25, 0.25]
                    primary = self._rng.choices(list(DIRECTIONS), weights=weights, k=1)[0]
                    v = self._spawn_vehicle(primary)
                    if not self._is_too_close_to_existing(v):
                        self.vehicles.append(v)

            # ── Машин хөдөлгөөн ─────────────────────────────────────
            moved_vehicles: list[dict[str, Any]] = []
            for vehicle in self.vehicles:
                mv = self._move_vehicle(vehicle, self.vehicles, dt)
                if mv is not None:
                    moved_vehicles.append(mv)
            self.vehicles = moved_vehicles

            self._refresh_green_times()
            return self._snapshot_locked()

    # ═══════════════════════════════════════════════════════
    # SNAPSHOT
    # ═══════════════════════════════════════════════════════
    def _snapshot_locked(self) -> SimulationState:
        waiting_count = sum(1 for v in self.vehicles if v.get("waiting"))
        total_q       = sum(self.queues.values())

        # Бодит KPI — датасеттэй харьцуулах боломжтой
        avg_wait = float(self._avg_wait(self.wait_times[self.mode]))
        throughput = round((self.total_passed / max(1, self.sim_time)) * 60.0, 2)

        # Тогтмол vs AI харьцуулалтын тооцоо
        fixed_avg = self._avg_wait(self.wait_times["fixed"])
        ai_avg    = self._avg_wait(self.wait_times["ai"])
        improvement = 0
        if fixed_avg > 0 and ai_avg > 0:
            improvement = int(round(((fixed_avg - ai_avg) / fixed_avg) * 100))

        return SimulationState(
            mode=self.mode,
            peakHour=self.peak_hour,
            heavyNorth=self.heavy_north,
            isRunning=self.is_running,
            speed=round(self.speed, 2),
            activeDir=self.active_dir,
            phaseTimer=int(math.ceil(self.phase_timer)),
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
            avgFixedWait=fixed_avg,
            avgAIWait=ai_avg,
            busDirections=list(self.bus_directions),
            emergencyDirections=list(self.emergency_directions),
            kpis={
                # Бодит KPI — датасеттэй шууд харьцуулах боломжтой
                "avg_wait_sec":          avg_wait,
                "throughput_per_min":    throughput,
                "avg_queue_depth":       round(total_q / max(1, len(self.queues)), 2),
                "total_queue":           total_q,
                "waiting_vehicles":      waiting_count,
                "active_vehicles":       len(self.vehicles),
                "queue_stability":       max(0, 100 - (max(self.queues.values()) - min(self.queues.values())) * 2),
                "improvement_pct":       improvement,
                # Датасетийн утгуудтай харьцуулах
                "dataset_fixed_green":   FIXED_GREEN_SEC,
                "dataset_cycle_sec":     FIXED_CYCLE_SEC,
                "current_phase_sec":     int(math.ceil(self.phase_timer)),
                "mode_discharge_rate":   self._discharge_rate,
                "weather_speed_factor":  round(self._weather_speed_factor, 2),
            },
            aiActivePhase=self._ai_state.ai_active_phase,
            aiDecisionReason=self._ai_state.ai_decision_reason,
            aiCongestionState=dict(self._ai_state.ai_congestion_state),
            antiGridlockActive=self._ai_state.anti_gridlock_active,
            pedestrianWaiting=dict(self._ai_state.pedestrian_waiting),
            emergencyActive=self._ai_state.emergency_active,
            neighborPressure=dict(self._ai_state.neighbor_pressure),
        )

    # ═══════════════════════════════════════════════════════
    # НИЙТИЙН API
    # ═══════════════════════════════════════════════════════
    async def get_state(self) -> SimulationState:
        async with self._lock:
            return self._snapshot_locked()

    async def start(self, payload: SimulationStartRequest) -> SimulationState:
        async with self._lock:
            if payload.mode is not None:
                self._set_mode_locked(payload.mode)
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

            self._apply_mode_params()
            self._refresh_green_times()

            state = self._snapshot_locked()

        await self._broadcast_state(state)
        return state

    async def set_mode(self, mode: str) -> SimulationState:
        async with self._lock:
            self._set_mode_locked(mode)
            state = self._snapshot_locked()
        await self._broadcast_state(state)
        return state

    def apply_dataset_config_sync(self, config: dict[str, Any]) -> None:
        """Dataset router-аас синхроноор дуудагдана (lock дотор)."""
        self._apply_dataset_config(config)

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
            ai_avg    = self._avg_wait(self.wait_times["ai"])
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
                queueStability=max(0, 100 - (max(self.queues.values()) - min(self.queues.values())) * 2),
            )

    async def get_queue_history(self) -> QueueHistoryResponse:
        async with self._lock:
            return QueueHistoryResponse(history=list(self.history))

    def _reset_runtime_state(self) -> None:
        self.is_running   = False
        self.active_dir   = "north"
        self.signal_state = "green"

        # Оргил цагт датасетийн анхны дараалалтайгаар эхлэнэ
        if self.peak_hour:
            self.queues = dict(PeakLoadConfig.PEAK_INITIAL_QUEUES)
        else:
            self.queues = dict(PeakLoadConfig.NORMAL_INITIAL_QUEUES)

        self.lane_queues  = self._create_initial_lane_queues(self.queues)
        self.phase_timer  = FIXED_GREEN_SEC if self.mode == "fixed" else 30
        self.total_passed = 0
        self.wait_times   = {"fixed": [], "ai": []}
        self.vehicles     = []
        self.intersections = self._create_intersections()
        self.sim_time     = 0
        self.history      = []
        self._frame       = 0
        self._vehicle_id  = 0
        self._second_accumulator = 0.0
        self._queue_snapshots    = []
        self.ai_runtime.reset()
        self._ai_state = AIRuntimeState()
        self._apply_mode_params()
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
        for ws in list(self._subscribers):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._subscribers.discard(ws)
