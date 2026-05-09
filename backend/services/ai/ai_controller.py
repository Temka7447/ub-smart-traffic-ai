"""
AI Traffic Controller — Adaptive Signal Optimization Engine
============================================================
For Ulaanbaatar smart city intersections.
Based on real UB dataset:
  - Rush hour 07-09 and 17-19 (CI ~0.72–0.74)
  - Max queue 33.5 vehicles, avg 14.67
  - Cycle 110-120s, green 55-65s
  - Intersections: Баруун 4 зам, Төв шуудан + 7 others

Architecture:
  1. DetectionAdapter   — normalises YOLO output, applies EMA smoothing
  2. PressureCalculator — weighted multi-factor scoring per phase
  3. PhaseScheduler     — decides next phase, respects conflict matrix
  4. TimingOptimiser    — computes adaptive green duration
  5. PedestrianScheduler— fairness-guaranteed pedestrian timing
  6. AntiGridlockGuard  — suppresses phases when outgoing lanes are blocked
  7. AIController       — orchestrates all of the above, one call per cycle
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from .lane_state import (
    ApproachArm, Direction, IntersectionSnapshot, LaneState,
    PedestrianState, PhaseID, PhaseTimingRecord, SignalState,
    TimeOfDayCategory, VehicleType, WeatherCondition, YOLODetection,
)
from .traffic_rules import (
    AI_TIMING_BOUNDS, MAX_STARVATION_SEC, PHASE_SIGNALS,
    TRADITIONAL_TIMING, TrafficRulesEngine,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 1. DETECTION ADAPTER
# ═══════════════════════════════════════════════════════

class DetectionAdapter:
    """
    Converts raw YOLO output (per-lane detection snapshots) into
    smoothed LaneState objects. Handles:
    - EMA noise filtering (combats 3.3 FPS jitter)
    - Spike rejection (ignore ±50% jump from EMA in one frame)
    - Emergency vehicle flagging
    """

    SPIKE_REJECTION_FACTOR = 0.5   # Reject if delta > 50% of current EMA

    def __init__(self, ema_alpha: float = 0.3):
        self.alpha = ema_alpha   # 0.3 = stable, 0.5 = responsive

    def ingest(
        self,
        lane_state: LaneState,
        detection: YOLODetection,
        cycle_dt: float,
    ) -> bool:
        """
        Update lane_state from a new YOLO detection.
        Returns True if detection was accepted, False if rejected as spike.
        """
        new_count = float(detection.vehicle_count_now)

        # Spike rejection: if count jumps by more than 50% of EMA in one cycle
        if lane_state.vehicle_count > 0:
            delta_ratio = abs(new_count - lane_state.vehicle_count) / lane_state.vehicle_count
            if delta_ratio > self.SPIKE_REJECTION_FACTOR and lane_state.vehicle_count > 3:
                logger.debug(
                    f"Spike rejected lane {detection.lane_id}: "
                    f"{lane_state.vehicle_count:.1f}→{new_count} "
                    f"({delta_ratio*100:.0f}% jump)"
                )
                # Use 50% blend instead of full value
                new_count = 0.5 * new_count + 0.5 * lane_state.vehicle_count

        lane_state.ingest_detection(detection, cycle_dt)
        return True

    @staticmethod
    def has_emergency_vehicle(detection: YOLODetection) -> bool:
        return VehicleType.EMERGENCY in detection.vehicle_types


# ═══════════════════════════════════════════════════════
# 2. PRESSURE CALCULATOR
# ═══════════════════════════════════════════════════════

@dataclass
class PressureResult:
    phase_id: PhaseID
    raw_pressure: float         # Incoming demand score
    outgoing_penalty: float     # Subtracted for blocked outgoing
    net_pressure: float         # raw_pressure - outgoing_penalty
    starvation_bonus: float     # Added for phases not served recently
    final_score: float          # net_pressure + starvation_bonus
    anti_gridlock_blocked: bool # True = this phase is fully suppressed
    reason: str


class PressureCalculator:
    """
    Computes a pressure score for each signal phase based on:

      pressure(phase) =
          w1 * normalized_queue +
          w2 * occupancy +
          w3 * wait_time_factor +
          w4 * inflow_rate +
          w5 * vehicle_weight_factor
        - outgoing_occupancy_penalty
        + starvation_bonus
        + emergency_bonus

    Weights calibrated to UB data:
      - Queue is dominant (avg 14.67, max 33.5)
      - Wait time secondary (drives fairness)
      - Outgoing penalty critical for anti-gridlock
    """

    # Incoming pressure weights (must sum to 1.0)
    W_QUEUE       = 0.35
    W_OCCUPANCY   = 0.25
    W_WAIT        = 0.20
    W_INFLOW      = 0.10
    W_VEH_WEIGHT  = 0.10   # buses/trucks count more than cars

    # Normalization references (from UB dataset)
    MAX_QUEUE     = 33.5   # observed maximum
    MAX_WAIT_SEC  = 120.0  # one full traditional cycle

    # Anti-gridlock: outgoing penalty parameters
    OUTGOING_WARN_THRESHOLD  = 0.70   # Start penalising at 70% outgoing occupancy
    OUTGOING_BLOCK_THRESHOLD = 0.88   # Fully suppress phase at 88% outgoing occupancy
    OUTGOING_MAX_PENALTY     = 1.5    # Max penalty score subtracted

    # Starvation bonus: grows linearly after phase not served for too long
    STARVATION_BONUS_PER_SEC = 0.008  # +0.008 per second over min service interval

    # Emergency override bonus
    EMERGENCY_BONUS = 5.0

    def compute_all(
        self,
        arms: dict[Direction, ApproachArm],
        pedestrians: dict[str, PedestrianState],
        time_since_last_served: dict[PhaseID, float],
        emergency_direction: Optional[Direction],
        weather: WeatherCondition,
        tod: TimeOfDayCategory,
    ) -> dict[PhaseID, PressureResult]:
        """
        Compute pressure scores for all non-ALL_RED phases.
        Returns a dict of PressureResult per phase.
        """
        results: dict[PhaseID, PressureResult] = {}

        # Weather factor: rain/snow/fog reduce effective throughput
        weather_factor = self._weather_factor(weather)

        for phase_id in [
            PhaseID.NS_STRAIGHT, PhaseID.NS_LEFT,
            PhaseID.EW_STRAIGHT, PhaseID.EW_LEFT,
            PhaseID.PEDESTRIAN_NS, PhaseID.PEDESTRIAN_EW,
        ]:
            result = self._compute_phase_pressure(
                phase_id=phase_id,
                arms=arms,
                pedestrians=pedestrians,
                time_since_last_served=time_since_last_served,
                emergency_direction=emergency_direction,
                weather_factor=weather_factor,
                tod=tod,
            )
            results[phase_id] = result

        return results

    def _compute_phase_pressure(
        self,
        phase_id: PhaseID,
        arms: dict[Direction, ApproachArm],
        pedestrians: dict[str, PedestrianState],
        time_since_last_served: dict[PhaseID, float],
        emergency_direction: Optional[Direction],
        weather_factor: float,
        tod: TimeOfDayCategory,
    ) -> PressureResult:

        # ── Step 1: Identify which arms are served by this phase ──
        served_arms = self._get_served_arms(phase_id, arms)
        outgoing_arms = self._get_outgoing_arms(phase_id, arms)

        # ── Step 2: Raw incoming pressure ──
        raw_pressure = 0.0

        if phase_id in (PhaseID.PEDESTRIAN_NS, PhaseID.PEDESTRIAN_EW):
            # Pedestrian pressure handled separately
            ped_keys = ['N', 'S'] if phase_id == PhaseID.PEDESTRIAN_NS else ['E', 'W']
            ped_demand = sum(
                pedestrians[k].priority_score
                for k in ped_keys
                if k in pedestrians
            )
            raw_pressure = ped_demand * 2.0  # scale to same order as vehicle pressure
        else:
            for arm in served_arms:
                raw_pressure += self._arm_pressure(arm, phase_id)

        raw_pressure *= weather_factor

        # ── Step 3: Outgoing lane penalty (ANTI-GRIDLOCK) ──
        outgoing_penalty = 0.0
        anti_gridlock_blocked = False

        for out_arm in outgoing_arms:
            occ = out_arm.outgoing_occupancy
            if occ >= self.OUTGOING_BLOCK_THRESHOLD:
                # Fully block this phase to prevent gridlock
                anti_gridlock_blocked = True
                outgoing_penalty = raw_pressure + 2.0   # ensures net < 0
                logger.info(
                    f"ANTI-GRIDLOCK: {phase_id.value} BLOCKED — "
                    f"{out_arm.direction.value} outgoing {occ:.0%} full"
                )
                break
            elif occ >= self.OUTGOING_WARN_THRESHOLD:
                # Penalise proportionally
                excess = (occ - self.OUTGOING_WARN_THRESHOLD) / (
                    self.OUTGOING_BLOCK_THRESHOLD - self.OUTGOING_WARN_THRESHOLD
                )
                outgoing_penalty += excess * self.OUTGOING_MAX_PENALTY

        net_pressure = max(0.0, raw_pressure - outgoing_penalty)

        # ── Step 4: Starvation bonus ──
        elapsed = time_since_last_served.get(phase_id, 0.0)
        max_starvation = MAX_STARVATION_SEC.get(phase_id, 120.0)
        starvation_ratio = max(0.0, elapsed - max_starvation * 0.5) / (max_starvation * 0.5)
        starvation_bonus = starvation_ratio * self.STARVATION_BONUS_PER_SEC * elapsed

        # Force-serve if at starvation limit (overrides anti-gridlock for peds)
        must_serve = False
        if phase_id in (PhaseID.PEDESTRIAN_NS, PhaseID.PEDESTRIAN_EW):
            ped_keys = ['N', 'S'] if phase_id == PhaseID.PEDESTRIAN_NS else ['E', 'W']
            must_serve = any(
                pedestrians[k].must_serve for k in ped_keys if k in pedestrians
            )
            if must_serve:
                anti_gridlock_blocked = False   # Pedestrian hard deadline overrides
                starvation_bonus += 10.0        # Very high priority
        else:
            if elapsed >= max_starvation:
                starvation_bonus += 3.0
                anti_gridlock_blocked = False   # Also override gridlock for vehicle starvation

        # ── Step 5: Emergency override ──
        emergency_bonus = 0.0
        if emergency_direction is not None:
            served_dirs = [arm.direction for arm in served_arms]
            if emergency_direction in served_dirs:
                emergency_bonus = self.EMERGENCY_BONUS
                anti_gridlock_blocked = False  # Emergency always overrides

        final_score = net_pressure + starvation_bonus + emergency_bonus

        reason = (
            f"raw={raw_pressure:.2f} "
            f"outPenalty={outgoing_penalty:.2f} "
            f"starvation={starvation_bonus:.2f} "
            f"emergency={emergency_bonus:.2f} "
            f"{'BLOCKED' if anti_gridlock_blocked else ''}"
        )

        return PressureResult(
            phase_id=phase_id,
            raw_pressure=raw_pressure,
            outgoing_penalty=outgoing_penalty,
            net_pressure=net_pressure,
            starvation_bonus=starvation_bonus,
            final_score=final_score if not anti_gridlock_blocked else -999.0,
            anti_gridlock_blocked=anti_gridlock_blocked,
            reason=reason,
        )

    def _arm_pressure(self, arm: ApproachArm, phase_id: PhaseID) -> float:
        """
        Compute pressure for one approach arm.
        Considers L1 (straight/right) and L2 (left-turn) separately.
        """
        l1 = arm.incoming_l1
        l2 = arm.incoming_l2

        # Select lanes relevant to this phase
        if phase_id in (PhaseID.NS_LEFT, PhaseID.EW_LEFT):
            lanes = [l2]   # Left-turn phase only serves L2
        else:
            lanes = [l1]   # Straight phase only serves L1

        pressure = 0.0
        for lane in lanes:
            q_norm = min(1.0, lane.queue_length / self.MAX_QUEUE)
            occ = lane.occupancy_pct
            wait_norm = min(1.0, lane.time_since_last_green / self.MAX_WAIT_SEC)
            inflow_norm = min(1.0, lane.inflow_rate / 20.0)  # normalise to 20 veh/cycle
            veh_weight = 1.0  # Could be 1.5 for buses/trucks (future)

            pressure += (
                self.W_QUEUE      * q_norm +
                self.W_OCCUPANCY  * occ +
                self.W_WAIT       * wait_norm +
                self.W_INFLOW     * inflow_norm +
                self.W_VEH_WEIGHT * veh_weight
            )

        return pressure

    @staticmethod
    def _get_served_arms(
        phase_id: PhaseID, arms: dict[Direction, ApproachArm]
    ) -> list[ApproachArm]:
        ns_phases = {PhaseID.NS_STRAIGHT, PhaseID.NS_LEFT}
        ew_phases = {PhaseID.EW_STRAIGHT, PhaseID.EW_LEFT}
        if phase_id in ns_phases:
            return [arms[d] for d in [Direction.NORTH, Direction.SOUTH] if d in arms]
        elif phase_id in ew_phases:
            return [arms[d] for d in [Direction.EAST, Direction.WEST] if d in arms]
        return []

    @staticmethod
    def _get_outgoing_arms(
        phase_id: PhaseID, arms: dict[Direction, ApproachArm]
    ) -> list[ApproachArm]:
        """
        Returns the approach arms whose OUTGOING lanes will be filled when this phase runs.
        NS_STRAIGHT active → vehicles exit into E/W outgoing lanes.
        """
        ns_phases = {PhaseID.NS_STRAIGHT, PhaseID.NS_LEFT}
        ew_phases = {PhaseID.EW_STRAIGHT, PhaseID.EW_LEFT}
        if phase_id in ns_phases:
            return [arms[d] for d in [Direction.EAST, Direction.WEST] if d in arms]
        elif phase_id in ew_phases:
            return [arms[d] for d in [Direction.NORTH, Direction.SOUTH] if d in arms]
        return []

    @staticmethod
    def _weather_factor(weather: WeatherCondition) -> float:
        return {
            WeatherCondition.CLEAR:  1.00,
            WeatherCondition.CLOUDY: 0.95,
            WeatherCondition.RAIN:   0.82,
            WeatherCondition.SNOW:   0.70,   # UB winters reduce throughput significantly
            WeatherCondition.FOG:    0.75,
        }.get(weather, 1.0)


# ═══════════════════════════════════════════════════════
# 3. TIMING OPTIMISER
# ═══════════════════════════════════════════════════════

class TimingOptimiser:
    """
    Given a selected phase and its pressure context, compute optimal green duration.

    Formula (Webster-inspired, adapted for adaptive control):
      base_green = lerp(min_green, max_green, load_ratio)
      adjusted = base_green * time_of_day_factor * weather_factor
      clamped = clamp(adjusted, min_green, max_green)

    Where load_ratio = (queue + occupancy) / 2, normalised 0-1.
    """

    def compute_green_duration(
        self,
        phase_id: PhaseID,
        pressure: PressureResult,
        arms: dict[Direction, ApproachArm],
        tod: TimeOfDayCategory,
        weather: WeatherCondition,
    ) -> float:
        min_g, max_g = AI_TIMING_BOUNDS.get(phase_id, (15.0, 60.0))

        # Special case: ALL_RED has fixed duration
        if phase_id == PhaseID.ALL_RED:
            return 4.0

        # Load ratio from raw pressure (already 0-1ish, cap at 1.0)
        load_ratio = min(1.0, pressure.raw_pressure / 2.0)

        # Interpolate between min and max
        base_green = min_g + load_ratio * (max_g - min_g)

        # Time-of-day multiplier: extend green during rush hours
        tod_factor = {
            TimeOfDayCategory.MORNING_RUSH: 1.25,   # 07-09h
            TimeOfDayCategory.EVENING_RUSH: 1.30,   # 17-19h (UB data shows 19h highest)
            TimeOfDayCategory.LUNCH_PEAK:   1.10,
            TimeOfDayCategory.MID_MORNING:  1.00,
            TimeOfDayCategory.AFTERNOON:    1.00,
            TimeOfDayCategory.NIGHT_QUIET:  0.80,   # shorter cycles at night
            TimeOfDayCategory.EVENING_WIND: 0.90,
        }.get(tod, 1.0)

        # Weather reduces green (slower through-put means less cleared per second)
        weather_factor = {
            WeatherCondition.SNOW: 1.20,   # Give MORE green time — vehicles clear slower
            WeatherCondition.FOG:  1.15,
            WeatherCondition.RAIN: 1.10,
            WeatherCondition.CLOUDY: 1.0,
            WeatherCondition.CLEAR: 1.0,
        }.get(weather, 1.0)

        adjusted = base_green * tod_factor * weather_factor
        return round(max(min_g, min(max_g, adjusted)), 1)


# ═══════════════════════════════════════════════════════
# 4. PEDESTRIAN SCHEDULER
# ═══════════════════════════════════════════════════════

class PedestrianScheduler:
    """
    Ensures pedestrian phases are inserted regularly and fairly.

    Rules:
    1. If any crosswalk hits MAX_RED_WAIT_SEC → immediate forced insertion.
    2. Otherwise, insert ped phase every N vehicle cycles (adaptive).
    3. Duration adapts to pedestrian count (12s–45s).
    4. Vehicle cycle is never interrupted mid-phase to insert ped.
    """

    def should_insert_pedestrian_phase(
        self,
        pedestrians: dict[str, PedestrianState],
        current_phase: PhaseID,
        phase_elapsed: float,
    ) -> Optional[PhaseID]:
        """
        Returns the pedestrian phase to insert next, or None.
        Only returns a phase if we are NOT currently in the middle of a vehicle phase.
        (i.e., only at the start of a cycle transition.)
        """
        # Hard deadline check
        ns_must = any(pedestrians[k].must_serve for k in ['N', 'S'] if k in pedestrians)
        ew_must = any(pedestrians[k].must_serve for k in ['E', 'W'] if k in pedestrians)

        if ns_must:
            return PhaseID.PEDESTRIAN_NS
        if ew_must:
            return PhaseID.PEDESTRIAN_EW

        # Priority score based scheduling (only when transitioning)
        ns_score = max((pedestrians[k].priority_score for k in ['N','S'] if k in pedestrians), default=0.0)
        ew_score = max((pedestrians[k].priority_score for k in ['E','W'] if k in pedestrians), default=0.0)

        PED_INSERT_THRESHOLD = 0.5
        if ns_score >= PED_INSERT_THRESHOLD and ns_score >= ew_score:
            return PhaseID.PEDESTRIAN_NS
        if ew_score >= PED_INSERT_THRESHOLD:
            return PhaseID.PEDESTRIAN_EW

        return None

    def update_wait_times(
        self,
        pedestrians: dict[str, PedestrianState],
        current_phase: PhaseID,
        dt: float,
    ):
        """Increment pedestrian wait times. Reset when ped phase is active."""
        for cw_id, ped in pedestrians.items():
            axis = 'NS' if cw_id in ('N', 'S') else 'EW'
            is_walking = (
                (axis == 'NS' and current_phase == PhaseID.PEDESTRIAN_NS) or
                (axis == 'EW' and current_phase == PhaseID.PEDESTRIAN_EW)
            )
            if is_walking:
                ped.wait_time_sec = 0.0
            else:
                ped.wait_time_sec += dt


# ═══════════════════════════════════════════════════════
# 5. PHASE SCHEDULER (CORE DECISION ENGINE)
# ═══════════════════════════════════════════════════════

class PhaseScheduler:
    """
    Selects the next phase to activate using the pressure scores.

    Algorithm:
    1. Collect all pressure scores from PressureCalculator.
    2. Check if pedestrian forced insertion is needed.
    3. Sort non-blocked phases by final_score DESC.
    4. Validate top candidate through TrafficRulesEngine.
    5. If invalid (min-green not elapsed), keep current phase.
    6. Always insert ALL_RED between incompatible phases.
    7. Return PhaseTimingRecord.
    """

    def __init__(self):
        self.rules = TrafficRulesEngine()
        self.timing = TimingOptimiser()
        self.ped_scheduler = PedestrianScheduler()

    def decide_next_phase(
        self,
        current_phase: PhaseID,
        phase_elapsed_sec: float,
        pressure_scores: dict[PhaseID, PressureResult],
        pedestrians: dict[str, PedestrianState],
        arms: dict[Direction, ApproachArm],
        tod: TimeOfDayCategory,
        weather: WeatherCondition,
    ) -> PhaseTimingRecord:

        # ── If in ALL_RED, just pick best candidate ──
        if current_phase == PhaseID.ALL_RED:
            return self._select_best_phase(
                pressure_scores, pedestrians, arms, tod, weather
            )

        # ── Check if pedestrian forced insertion needed ──
        forced_ped = self.ped_scheduler.should_insert_pedestrian_phase(
            pedestrians, current_phase, phase_elapsed_sec
        )

        # ── Check if current phase should continue ──
        max_g = AI_TIMING_BOUNDS.get(current_phase, (15.0, 60.0))[1]
        min_g = AI_TIMING_BOUNDS.get(current_phase, (15.0, 60.0))[0]

        if phase_elapsed_sec < min_g:
            # Must stay in current phase (min green constraint)
            current_score = pressure_scores.get(current_phase)
            duration = self.timing.compute_green_duration(
                current_phase, current_score, arms, tod, weather
            ) if current_score else min_g
            return PhaseTimingRecord(
                phase_id=current_phase,
                green_duration_sec=duration,
                reason=f"MIN_GREEN: {phase_elapsed_sec:.1f}s/{min_g}s elapsed",
                pressure_score=current_score.final_score if current_score else 0.0,
            )

        # ── Decide whether to switch ──
        if forced_ped is not None:
            # Insert ALL_RED first if needed
            if self.rules.requires_all_red_between(current_phase, forced_ped):
                return PhaseTimingRecord(
                    phase_id=PhaseID.ALL_RED,
                    green_duration_sec=4.0,
                    reason=f"ALL_RED before forced PED phase",
                    pressure_score=0.0,
                )
            # Then serve pedestrian
            ped_score = pressure_scores.get(forced_ped)
            ped_duration = max(12.0, ped_score.raw_pressure * 20.0) if ped_score else 20.0
            return PhaseTimingRecord(
                phase_id=forced_ped,
                green_duration_sec=min(45.0, ped_duration),
                reason="FORCED_PEDESTRIAN: max wait exceeded",
                pressure_score=ped_score.final_score if ped_score else 0.0,
            )

        # ── Check if current phase should extend (max not reached + still high pressure) ──
        current_score = pressure_scores.get(current_phase)
        if current_score and phase_elapsed_sec < max_g:
            # Compare current phase score vs best alternative
            best_alternative = max(
                (v for k, v in pressure_scores.items() if k != current_phase and not v.anti_gridlock_blocked),
                key=lambda r: r.final_score,
                default=None,
            )
            if best_alternative and best_alternative.final_score > current_score.final_score * 1.3:
                # Switch if alternative is >30% better
                return self._transition_to(
                    current_phase, best_alternative, pressure_scores, arms, tod, weather
                )
            else:
                # Extend current phase
                duration = self.timing.compute_green_duration(
                    current_phase, current_score, arms, tod, weather
                )
                return PhaseTimingRecord(
                    phase_id=current_phase,
                    green_duration_sec=duration,
                    reason=f"EXTEND: score={current_score.final_score:.2f}",
                    pressure_score=current_score.final_score,
                )

        # ── Max green reached → must switch ──
        return self._select_best_phase(pressure_scores, pedestrians, arms, tod, weather)

    def _select_best_phase(
        self,
        pressure_scores: dict[PhaseID, PressureResult],
        pedestrians: dict[str, PedestrianState],
        arms: dict[Direction, ApproachArm],
        tod: TimeOfDayCategory,
        weather: WeatherCondition,
    ) -> PhaseTimingRecord:
        # Sort non-blocked phases by final_score
        candidates = sorted(
            [r for r in pressure_scores.values() if not r.anti_gridlock_blocked],
            key=lambda r: r.final_score,
            reverse=True,
        )
        if not candidates:
            # All phases blocked by anti-gridlock — serve ALL_RED to let outgoing drain
            return PhaseTimingRecord(
                phase_id=PhaseID.ALL_RED,
                green_duration_sec=5.0,
                reason="ALL_PHASES_BLOCKED: outgoing congestion, waiting for drain",
                pressure_score=0.0,
                anti_gridlock_active=True,
            )

        best = candidates[0]
        duration = self.timing.compute_green_duration(
            best.phase_id, best, arms, tod, weather
        )
        return PhaseTimingRecord(
            phase_id=best.phase_id,
            green_duration_sec=duration,
            reason=f"BEST_PHASE: {best.reason}",
            pressure_score=best.final_score,
            anti_gridlock_active=best.outgoing_penalty > 0,
        )

    def _transition_to(
        self,
        current_phase: PhaseID,
        target: PressureResult,
        pressure_scores: dict[PhaseID, PressureResult],
        arms: dict[Direction, ApproachArm],
        tod: TimeOfDayCategory,
        weather: WeatherCondition,
    ) -> PhaseTimingRecord:
        if self.rules.requires_all_red_between(current_phase, target.phase_id):
            return PhaseTimingRecord(
                phase_id=PhaseID.ALL_RED,
                green_duration_sec=4.0,
                reason=f"ALL_RED transition to {target.phase_id.value}",
                pressure_score=0.0,
            )
        duration = self.timing.compute_green_duration(
            target.phase_id, target, arms, tod, weather
        )
        return PhaseTimingRecord(
            phase_id=target.phase_id,
            green_duration_sec=duration,
            reason=f"SWITCH: {target.reason}",
            pressure_score=target.final_score,
            anti_gridlock_active=target.outgoing_penalty > 0,
        )


# ═══════════════════════════════════════════════════════
# 6. MULTI-INTERSECTION COORDINATOR
# ═══════════════════════════════════════════════════════

class MultiIntersectionCoordinator:
    """
    Coordinates signal timing across the 3×3 grid of 9 intersections.
    Implements green wave / corridor progression for arterials.

    Grid layout (matches frontend MultiIntersectionGrid.jsx):
        [0,0] [0,1] [0,2]    INT 0  INT 1  INT 2
        [1,0] [1,1] [1,2]    INT 3  INT 4  INT 5
        [2,0] [2,1] [2,2]    INT 6  INT 7  INT 8

    Neighbor relationships:
        INT 0 ↔ INT 1 (E/W corridor row 0)
        INT 3 ↔ INT 4 ↔ INT 5 (E/W corridor row 1)
        INT 0 ↔ INT 3 ↔ INT 6 (N/S corridor col 0)
        etc.
    """

    GRID_ROWS = 3
    GRID_COLS = 3

    # Typical arterial travel time between adjacent intersections (seconds)
    # Based on UB urban block length ~200-300m at avg speed 30 km/h
    INTER_TRAVEL_TIME_SEC = 24.0  # 240m / 10 m/s = 24s

    @staticmethod
    def get_neighbors(intersection_id: int) -> dict[str, Optional[int]]:
        """
        Returns adjacent intersection IDs for a given intersection.
        None = no neighbor in that direction (edge of grid).
        """
        row = intersection_id // 3
        col = intersection_id % 3
        return {
            'north': (row - 1) * 3 + col if row > 0 else None,
            'south': (row + 1) * 3 + col if row < 2 else None,
            'east':  row * 3 + (col + 1) if col < 2 else None,
            'west':  row * 3 + (col - 1) if col > 0 else None,
        }

    def compute_green_wave_offset(
        self,
        intersection_id: int,
        current_snapshots: dict[int, IntersectionSnapshot],
        cycle_length: float,
    ) -> float:
        """
        Compute the recommended phase offset for this intersection to
        enable a green wave along the E/W or N/S corridor.

        Returns: offset_seconds (0 to cycle_length)

        Green wave formula:
            offset_i = (distance_from_reference / speed) % cycle_length
        """
        col = intersection_id % 3
        # Offset along the E/W corridor: col 0 = 0s, col 1 = 24s, col 2 = 48s
        ew_offset = col * self.INTER_TRAVEL_TIME_SEC
        return ew_offset % cycle_length

    def propagate_pressure(
        self,
        intersection_id: int,
        own_pressure: float,
        all_pressures: dict[int, float],
    ) -> float:
        """
        Adjust own pressure based on neighbor congestion.
        If upstream neighbors are heavily congested, pre-emptively extend green
        to prevent spillback.

        Returns: adjusted pressure multiplier (1.0 = no change)
        """
        neighbors = self.get_neighbors(intersection_id)
        neighbor_pressures = [
            all_pressures.get(nid, 0.0)
            for nid in neighbors.values()
            if nid is not None and nid in all_pressures
        ]

        if not neighbor_pressures:
            return 1.0

        avg_neighbor = sum(neighbor_pressures) / len(neighbor_pressures)

        # If neighbors are heavily congested (>0.7), add spillback prevention pressure
        if avg_neighbor > 0.7:
            spillback_factor = 1.0 + (avg_neighbor - 0.7) * 0.5   # max 1.15x
            return spillback_factor

        return 1.0


# ═══════════════════════════════════════════════════════
# 7. MAIN AI CONTROLLER — INTERSECTION LEVEL
# ═══════════════════════════════════════════════════════

class IntersectionAIController:
    """
    Top-level controller for one intersection.
    Called once per simulation cycle (default: every 1 second).

    Usage:
        controller = IntersectionAIController(intersection_id=0, ai_mode=True)
        controller.ingest_detections(detections_dict)
        decision = controller.tick(dt=1.0)
        snapshot = controller.get_snapshot()
    """

    CYCLE_INTERVAL_SEC = 1.0   # Control loop frequency

    def __init__(
        self,
        intersection_id: int,
        intersection_name: str,
        ai_mode: bool = True,
    ):
        self.intersection_id = intersection_id
        self.intersection_name = intersection_name
        self.ai_mode = ai_mode

        # Arms
        self.arms: dict[Direction, ApproachArm] = {
            d: ApproachArm(direction=d, intersection_id=intersection_id)
            for d in Direction
        }

        # Pedestrian crosswalks (one per arm)
        self.pedestrians: dict[str, PedestrianState] = {
            d.value: PedestrianState(crosswalk_id=d.value)
            for d in Direction
        }

        # Phase tracking
        self.current_phase: PhaseID = PhaseID.ALL_RED
        self.phase_elapsed_sec: float = 0.0
        self.phase_duration_sec: float = 4.0
        self.next_phase: Optional[PhaseID] = PhaseID.NS_STRAIGHT

        # Time since each phase was last served (for starvation tracking)
        self.time_since_served: dict[PhaseID, float] = {p: 0.0 for p in PhaseID}

        # Metrics
        self.total_vehicles_passed: int = 0
        self.emergency_direction: Optional[Direction] = None
        self.weather: WeatherCondition = WeatherCondition.CLEAR
        self.tod: TimeOfDayCategory = TimeOfDayCategory.MID_MORNING

        # Components
        self.detection_adapter = DetectionAdapter()
        self.pressure_calc = PressureCalculator()
        self.scheduler = PhaseScheduler()
        self.ped_scheduler = PedestrianScheduler()

        # Traditional cycle state (used when ai_mode=False)
        self._trad_cycle_index: int = 0
        self._trad_cycle_order = [
            PhaseID.NS_STRAIGHT, PhaseID.ALL_RED,
            PhaseID.NS_LEFT,     PhaseID.ALL_RED,
            PhaseID.EW_STRAIGHT, PhaseID.ALL_RED,
            PhaseID.EW_LEFT,     PhaseID.ALL_RED,
            PhaseID.PEDESTRIAN_NS, PhaseID.ALL_RED,
            PhaseID.PEDESTRIAN_EW, PhaseID.ALL_RED,
        ]

        # Logging
        self._decision_log: list[str] = []

    def ingest_detections(self, detections: dict[int, YOLODetection], dt: float):
        """
        Feed new YOLO detection data into the lane states.
        detections: {lane_id: YOLODetection}
        Lane ID mapping:
            1 = North L1, 2 = North L2, 3 = North L3, 4 = North L4
            5 = South L1, 6 = South L2, ...  (per-direction offset)
        """
        # Map flat lane IDs to arm+lane slots
        lane_map = {
            1: (Direction.NORTH, 'l1'), 2: (Direction.NORTH, 'l2'),
            3: (Direction.NORTH, 'l3'), 4: (Direction.NORTH, 'l4'),
            5: (Direction.SOUTH, 'l1'), 6: (Direction.SOUTH, 'l2'),
            7: (Direction.SOUTH, 'l3'), 8: (Direction.SOUTH, 'l4'),
            9: (Direction.EAST,  'l1'), 10: (Direction.EAST,  'l2'),
            11: (Direction.EAST, 'l3'), 12: (Direction.EAST,  'l4'),
            13: (Direction.WEST, 'l1'), 14: (Direction.WEST,  'l2'),
            15: (Direction.WEST, 'l3'), 16: (Direction.WEST,  'l4'),
        }
        for lane_id, detection in detections.items():
            if lane_id not in lane_map:
                continue
            direction, slot = lane_map[lane_id]
            arm = self.arms[direction]
            lane: LaneState = getattr(arm, f'incoming_{slot}' if slot in ('l1','l2') else f'outgoing_{slot}')
            self.detection_adapter.ingest(lane, detection, dt)

            # Emergency vehicle detection
            if self.detection_adapter.has_emergency_vehicle(detection):
                self.emergency_direction = direction
                logger.warning(f"[INT-{self.intersection_id}] EMERGENCY in {direction.value}")

    def tick(self, dt: float) -> PhaseTimingRecord:
        """
        Main control loop tick. Call once per control cycle.
        Returns the PhaseTimingRecord for the current decision.
        """
        # Update time-of-day
        self.tod = self._get_tod()

        # Update pedestrian wait times
        self.ped_scheduler.update_wait_times(self.pedestrians, self.current_phase, dt)

        # Increment phase elapsed time
        self.phase_elapsed_sec += dt

        # Increment starvation timers for all non-active phases
        for phase in PhaseID:
            if phase != self.current_phase:
                self.time_since_served[phase] += dt
            else:
                self.time_since_served[phase] = 0.0

        # ── Traditional mode: fixed cycle ──
        if not self.ai_mode:
            return self._traditional_tick(dt)

        # ── AI mode: check if phase should change ──
        if self.phase_elapsed_sec >= self.phase_duration_sec:
            # Phase duration expired → compute next phase
            pressure_scores = self.pressure_calc.compute_all(
                arms=self.arms,
                pedestrians=self.pedestrians,
                time_since_last_served=self.time_since_served,
                emergency_direction=self.emergency_direction,
                weather=self.weather,
                tod=self.tod,
            )

            decision = self.scheduler.decide_next_phase(
                current_phase=self.current_phase,
                phase_elapsed_sec=self.phase_elapsed_sec,
                pressure_scores=pressure_scores,
                pedestrians=self.pedestrians,
                arms=self.arms,
                tod=self.tod,
                weather=self.weather,
            )

            self._apply_decision(decision)
            self._log_decision(decision, pressure_scores)
            return decision

        # Phase still running — return current state unchanged
        current_score = PressureResult(
            phase_id=self.current_phase,
            raw_pressure=0.0, outgoing_penalty=0.0, net_pressure=0.0,
            starvation_bonus=0.0,
            final_score=0.0, anti_gridlock_blocked=False,
            reason="phase running"
        )
        return PhaseTimingRecord(
            phase_id=self.current_phase,
            green_duration_sec=self.phase_duration_sec,
            reason="RUNNING",
            pressure_score=0.0,
        )

    def _traditional_tick(self, dt: float) -> PhaseTimingRecord:
        """Fixed-timing traditional signal cycle."""
        phase = self._trad_cycle_order[self._trad_cycle_index % len(self._trad_cycle_order)]
        duration = TRADITIONAL_TIMING.get(phase, 30.0)

        if self.phase_elapsed_sec >= duration:
            self._trad_cycle_index += 1
            next_phase = self._trad_cycle_order[self._trad_cycle_index % len(self._trad_cycle_order)]
            self.current_phase = next_phase
            self.phase_elapsed_sec = 0.0
            self.phase_duration_sec = TRADITIONAL_TIMING.get(next_phase, 30.0)
            self._apply_signals()

        return PhaseTimingRecord(
            phase_id=self.current_phase,
            green_duration_sec=self.phase_duration_sec,
            reason="TRADITIONAL_FIXED",
            pressure_score=0.0,
        )

    def _apply_decision(self, decision: PhaseTimingRecord):
        """Apply a phase decision — update signal states."""
        self.current_phase = decision.phase_id
        self.phase_elapsed_sec = 0.0
        self.phase_duration_sec = decision.green_duration_sec
        self._apply_signals()

        # Clear emergency after it has been served
        if (self.emergency_direction and
                decision.emergency_override or
                self.phase_elapsed_sec > 30):
            self.emergency_direction = None

    def _apply_signals(self):
        """Write signal states to all arm lane objects."""
        signals = TrafficRulesEngine.get_signals_for_phase(self.current_phase)
        for direction, signal_state in signals.items():
            arm = self.arms[direction]
            arm.incoming_l1.current_signal = signal_state
            arm.incoming_l2.current_signal = signal_state

    def _log_decision(self, decision: PhaseTimingRecord, scores: dict):
        entry = (
            f"[INT-{self.intersection_id}] "
            f"→{decision.phase_id.value} "
            f"dur={decision.green_duration_sec:.0f}s "
            f"score={decision.pressure_score:.2f} "
            f"{'[GRIDLOCK]' if decision.anti_gridlock_active else ''} "
            f"{'[EMERGENCY]' if decision.emergency_override else ''}"
        )
        self._decision_log.append(entry)
        if len(self._decision_log) > 50:
            self._decision_log.pop(0)
        logger.info(entry)

    def get_snapshot(self) -> IntersectionSnapshot:
        """Return serializable state for WebSocket broadcast."""
        signals = TrafficRulesEngine.get_signals_for_phase(self.current_phase)
        total_queue = sum(
            arm.total_incoming_queue for arm in self.arms.values()
        )
        avg_wait = sum(
            arm.max_wait_sec for arm in self.arms.values()
        ) / 4.0

        return IntersectionSnapshot(
            intersection_id=self.intersection_id,
            intersection_name=self.intersection_name,
            timestamp=time.time(),
            north_signal=signals.get(Direction.NORTH, SignalState.RED),
            south_signal=signals.get(Direction.SOUTH, SignalState.RED),
            east_signal=signals.get(Direction.EAST, SignalState.RED),
            west_signal=signals.get(Direction.WEST, SignalState.RED),
            active_phase=self.current_phase,
            phase_elapsed_sec=round(self.phase_elapsed_sec, 1),
            phase_remaining_sec=round(
                max(0.0, self.phase_duration_sec - self.phase_elapsed_sec), 1
            ),
            avg_wait_sec=round(avg_wait, 1),
            total_queue=int(total_queue),
            congestion_index=round(
                min(1.0, total_queue / (4 * 33.5)), 3   # normalised to UB max queue
            ),
            throughput_vph=self.total_vehicles_passed * 60,   # rough estimate
            ai_mode=self.ai_mode,
            ai_decision_reason=self._decision_log[-1] if self._decision_log else "",
            anti_gridlock_active=any(
                arm.outgoing_blocked for arm in self.arms.values()
            ),
            pedestrian_waiting={
                k: v.waiting_count for k, v in self.pedestrians.items()
            },
            emergency_active=self.emergency_direction is not None,
            neighbor_pressure={},
        )

    @staticmethod
    def _get_tod() -> TimeOfDayCategory:
        """Classify current real time into a UB-calibrated time-of-day bucket."""
        hour = time.localtime().tm_hour
        if 7 <= hour < 10:
            return TimeOfDayCategory.MORNING_RUSH
        elif 10 <= hour < 12:
            return TimeOfDayCategory.MID_MORNING
        elif 12 <= hour < 14:
            return TimeOfDayCategory.LUNCH_PEAK
        elif 14 <= hour < 17:
            return TimeOfDayCategory.AFTERNOON
        elif 17 <= hour < 20:
            return TimeOfDayCategory.EVENING_RUSH
        elif 20 <= hour < 24:
            return TimeOfDayCategory.EVENING_WIND
        else:
            return TimeOfDayCategory.NIGHT_QUIET
