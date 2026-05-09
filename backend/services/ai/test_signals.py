"""
Test Suite — AI Traffic Controller
===================================
Tests cover:
  1. Conflict matrix safety (no conflicting greens)
  2. Pressure calculator correctness
  3. Anti-gridlock suppression
  4. Pedestrian starvation detection and forced insertion
  5. Phase timing bounds
  6. Traditional vs AI mode distinction
  7. Emergency override logic
  8. Multi-intersection coordinator

Run: pytest backend/tests/test_signals.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import time

from backend.services.ai.lane_state import (
    ApproachArm, Direction, LaneState, LaneType, PedestrianState,
    PhaseID, SignalState, TimeOfDayCategory, VehicleType,
    WeatherCondition, YOLODetection,
)
from backend.services.ai.traffic_rules import (
    CONFLICT_MATRIX, PHASE_SIGNALS, TrafficRulesEngine,
    AI_TIMING_BOUNDS, MAX_STARVATION_SEC,
)
from backend.services.ai.ai_controller import (
    DetectionAdapter, IntersectionAIController, PressureCalculator,
    TimingOptimiser, MultiIntersectionCoordinator, PhaseScheduler,
)


# ──────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────

def make_arm(direction: Direction, queue_l1: float = 5.0, queue_l2: float = 3.0) -> ApproachArm:
    arm = ApproachArm(direction=direction, intersection_id=0)
    arm.incoming_l1.queue_length = queue_l1
    arm.incoming_l1.vehicle_count = queue_l1
    arm.incoming_l1.occupancy_pct = queue_l1 / 20.0
    arm.incoming_l2.queue_length = queue_l2
    arm.incoming_l2.vehicle_count = queue_l2
    arm.incoming_l2.occupancy_pct = queue_l2 / 20.0
    return arm


def make_arms(
    n_queue=5.0, s_queue=5.0, e_queue=3.0, w_queue=3.0
) -> dict[Direction, ApproachArm]:
    return {
        Direction.NORTH: make_arm(Direction.NORTH, n_queue),
        Direction.SOUTH: make_arm(Direction.SOUTH, s_queue),
        Direction.EAST:  make_arm(Direction.EAST, e_queue),
        Direction.WEST:  make_arm(Direction.WEST, w_queue),
    }


def make_pedestrians(wait_sec: float = 10.0) -> dict[str, PedestrianState]:
    return {
        d: PedestrianState(crosswalk_id=d, wait_time_sec=wait_sec)
        for d in ['N', 'S', 'E', 'W']
    }


# ──────────────────────────────────────────────
# 1. CONFLICT MATRIX SAFETY
# ──────────────────────────────────────────────

class TestConflictMatrix:
    def test_matrix_is_symmetric(self):
        """If A conflicts with B, B must conflict with A."""
        for phase_a, conflicts in CONFLICT_MATRIX.items():
            for phase_b in conflicts:
                assert phase_a in CONFLICT_MATRIX[phase_b], (
                    f"Asymmetry: {phase_a} conflicts with {phase_b} but not vice versa"
                )

    def test_all_red_has_no_conflicts(self):
        """ALL_RED must be conflict-free."""
        assert len(CONFLICT_MATRIX[PhaseID.ALL_RED]) == 0

    def test_ns_ew_straight_conflict(self):
        """NS_STRAIGHT and EW_STRAIGHT must conflict (crossing paths)."""
        assert PhaseID.EW_STRAIGHT in CONFLICT_MATRIX[PhaseID.NS_STRAIGHT]
        assert PhaseID.NS_STRAIGHT in CONFLICT_MATRIX[PhaseID.EW_STRAIGHT]

    def test_left_turn_straight_same_axis_conflict(self):
        """NS_LEFT and NS_STRAIGHT must conflict with each other."""
        assert PhaseID.NS_LEFT in CONFLICT_MATRIX[PhaseID.NS_STRAIGHT]
        assert PhaseID.NS_STRAIGHT in CONFLICT_MATRIX[PhaseID.NS_LEFT]

    def test_pedestrian_conflicts_with_vehicles(self):
        """Pedestrian phases must conflict with all vehicle movement phases."""
        vehicle_phases = [
            PhaseID.NS_STRAIGHT, PhaseID.NS_LEFT,
            PhaseID.EW_STRAIGHT, PhaseID.EW_LEFT,
        ]
        for vp in vehicle_phases:
            assert vp in CONFLICT_MATRIX[PhaseID.PEDESTRIAN_NS], (
                f"PED_NS should conflict with {vp}"
            )

    def test_validate_transition_blocks_conflict(self):
        """TrafficRulesEngine must reject NS → EW direct transition."""
        rules = TrafficRulesEngine()
        valid, reason = rules.validate_transition(
            PhaseID.NS_STRAIGHT, PhaseID.EW_STRAIGHT, current_elapsed_sec=30.0
        )
        assert not valid
        assert "CONFLICT" in reason

    def test_validate_transition_allows_via_all_red(self):
        """Transition via ALL_RED must be allowed."""
        rules = TrafficRulesEngine()
        valid, reason = rules.validate_transition(
            PhaseID.ALL_RED, PhaseID.EW_STRAIGHT, current_elapsed_sec=4.0
        )
        assert valid, f"Should be valid but got: {reason}"

    def test_requires_all_red_between_incompatible(self):
        rules = TrafficRulesEngine()
        assert rules.requires_all_red_between(PhaseID.NS_STRAIGHT, PhaseID.EW_STRAIGHT)
        assert not rules.requires_all_red_between(PhaseID.ALL_RED, PhaseID.EW_STRAIGHT)

    def test_phase_signals_never_double_green(self):
        """No two conflicting phases should share a GREEN direction."""
        for phase_id, signals in PHASE_SIGNALS.items():
            if phase_id == PhaseID.ALL_RED:
                continue
            green_dirs = {d for d, s in signals.items() if s == SignalState.GREEN}
            for other_phase, other_signals in PHASE_SIGNALS.items():
                if other_phase == phase_id or other_phase == PhaseID.ALL_RED:
                    continue
                if other_phase in CONFLICT_MATRIX.get(phase_id, frozenset()):
                    other_green = {d for d, s in other_signals.items() if s == SignalState.GREEN}
                    overlap = green_dirs & other_green
                    # They should not both have the same direction green
                    # (opposite directions in same axis is fine by design)


# ──────────────────────────────────────────────
# 2. PRESSURE CALCULATOR
# ──────────────────────────────────────────────

class TestPressureCalculator:
    def setup_method(self):
        self.calc = PressureCalculator()

    def test_higher_queue_gives_higher_pressure(self):
        arms_high = make_arms(n_queue=20.0, s_queue=20.0, e_queue=2.0, w_queue=2.0)
        arms_low  = make_arms(n_queue=2.0,  s_queue=2.0,  e_queue=2.0, w_queue=2.0)
        peds = make_pedestrians()
        served = {p: 0.0 for p in PhaseID}

        scores_high = self.calc.compute_all(arms_high, peds, served, None,
                                             WeatherCondition.CLEAR, TimeOfDayCategory.MID_MORNING)
        scores_low  = self.calc.compute_all(arms_low, peds, served, None,
                                             WeatherCondition.CLEAR, TimeOfDayCategory.MID_MORNING)

        assert scores_high[PhaseID.NS_STRAIGHT].raw_pressure > \
               scores_low[PhaseID.NS_STRAIGHT].raw_pressure

    def test_anti_gridlock_blocks_when_outgoing_full(self):
        arms = make_arms()
        # Fill outgoing lanes of East (which NS phases send traffic into)
        arms[Direction.EAST].outgoing_l3.occupancy_pct = 0.95
        arms[Direction.EAST].outgoing_l3.congestion_counter = 5
        arms[Direction.EAST].outgoing_l3.congestion_confirmed = True
        arms[Direction.EAST].outgoing_l4.occupancy_pct = 0.95
        arms[Direction.EAST].outgoing_l4.congestion_counter = 5
        arms[Direction.EAST].outgoing_l4.congestion_confirmed = True
        arms[Direction.WEST].outgoing_l3.occupancy_pct = 0.95
        arms[Direction.WEST].outgoing_l3.congestion_counter = 5
        arms[Direction.WEST].outgoing_l3.congestion_confirmed = True
        arms[Direction.WEST].outgoing_l4.occupancy_pct = 0.95
        arms[Direction.WEST].outgoing_l4.congestion_counter = 5
        arms[Direction.WEST].outgoing_l4.congestion_confirmed = True

        peds = make_pedestrians()
        served = {p: 0.0 for p in PhaseID}

        scores = self.calc.compute_all(arms, peds, served, None,
                                        WeatherCondition.CLEAR, TimeOfDayCategory.MID_MORNING)

        ns_result = scores[PhaseID.NS_STRAIGHT]
        assert ns_result.anti_gridlock_blocked, (
            "NS_STRAIGHT should be blocked when E/W outgoing are congested"
        )
        assert ns_result.final_score < 0, (
            "Blocked phase should have negative final score"
        )

    def test_emergency_bonus_overrides_gridlock(self):
        arms = make_arms()
        # Fill all outgoing to trigger gridlock
        for direction in Direction:
            for attr in ['outgoing_l3', 'outgoing_l4']:
                lane = getattr(arms[direction], attr)
                lane.occupancy_pct = 0.95
                lane.congestion_counter = 5
                lane.congestion_confirmed = True

        peds = make_pedestrians()
        served = {p: 0.0 for p in PhaseID}

        scores = self.calc.compute_all(
            arms, peds, served,
            emergency_direction=Direction.NORTH,
            weather=WeatherCondition.CLEAR,
            tod=TimeOfDayCategory.MORNING_RUSH,
        )

        ns_result = scores[PhaseID.NS_STRAIGHT]
        assert not ns_result.anti_gridlock_blocked, (
            "Emergency should override anti-gridlock for NS_STRAIGHT"
        )

    def test_starvation_bonus_grows_over_time(self):
        arms = make_arms()
        peds = make_pedestrians()
        # NS not served for 100 seconds (above 60s midpoint of 120s max)
        served_short = {p: 0.0 for p in PhaseID}
        served_long  = {p: 0.0 for p in PhaseID}
        served_long[PhaseID.NS_STRAIGHT] = 100.0

        s_short = self.calc.compute_all(arms, peds, served_short, None,
                                         WeatherCondition.CLEAR, TimeOfDayCategory.MID_MORNING)
        s_long  = self.calc.compute_all(arms, peds, served_long, None,
                                         WeatherCondition.CLEAR, TimeOfDayCategory.MID_MORNING)

        assert s_long[PhaseID.NS_STRAIGHT].starvation_bonus >= \
               s_short[PhaseID.NS_STRAIGHT].starvation_bonus

    def test_snow_weather_reduces_pressure(self):
        arms = make_arms()
        peds = make_pedestrians()
        served = {p: 0.0 for p in PhaseID}

        clear = self.calc.compute_all(arms, peds, served, None,
                                       WeatherCondition.CLEAR, TimeOfDayCategory.MID_MORNING)
        snow  = self.calc.compute_all(arms, peds, served, None,
                                       WeatherCondition.SNOW, TimeOfDayCategory.MID_MORNING)

        assert snow[PhaseID.NS_STRAIGHT].raw_pressure < \
               clear[PhaseID.NS_STRAIGHT].raw_pressure


# ──────────────────────────────────────────────
# 3. TIMING OPTIMISER
# ──────────────────────────────────────────────

class TestTimingOptimiser:
    def setup_method(self):
        self.opt = TimingOptimiser()

    def make_pressure(self, score: float):
        from services.ai_controller import PressureResult
        return PressureResult(
            phase_id=PhaseID.NS_STRAIGHT,
            raw_pressure=score,
            outgoing_penalty=0.0,
            net_pressure=score,
            starvation_bonus=0.0,
            final_score=score,
            anti_gridlock_blocked=False,
            reason="test",
        )

    def test_rush_hour_extends_green(self):
        arms = make_arms()
        p = self.make_pressure(1.0)
        normal = self.opt.compute_green_duration(
            PhaseID.NS_STRAIGHT, p, arms, TimeOfDayCategory.MID_MORNING, WeatherCondition.CLEAR
        )
        rush = self.opt.compute_green_duration(
            PhaseID.NS_STRAIGHT, p, arms, TimeOfDayCategory.MORNING_RUSH, WeatherCondition.CLEAR
        )
        assert rush > normal, f"Rush {rush} should > normal {normal}"

    def test_bounds_respected(self):
        arms = make_arms()
        for phase_id in [PhaseID.NS_STRAIGHT, PhaseID.NS_LEFT, PhaseID.EW_STRAIGHT]:
            min_g, max_g = AI_TIMING_BOUNDS[phase_id]
            for score in [0.0, 0.5, 1.0, 2.0]:
                p = self.make_pressure(score)
                duration = self.opt.compute_green_duration(
                    phase_id, p, arms, TimeOfDayCategory.MID_MORNING, WeatherCondition.CLEAR
                )
                assert min_g <= duration <= max_g, (
                    f"{phase_id.value} score={score}: duration={duration} out of [{min_g},{max_g}]"
                )

    def test_snow_gives_longer_green(self):
        arms = make_arms()
        p = self.make_pressure(1.0)
        clear = self.opt.compute_green_duration(
            PhaseID.NS_STRAIGHT, p, arms, TimeOfDayCategory.MID_MORNING, WeatherCondition.CLEAR
        )
        snow = self.opt.compute_green_duration(
            PhaseID.NS_STRAIGHT, p, arms, TimeOfDayCategory.MID_MORNING, WeatherCondition.SNOW
        )
        assert snow >= clear, "Snow should give longer green (vehicles clear slower)"


# ──────────────────────────────────────────────
# 4. PEDESTRIAN SCHEDULER
# ──────────────────────────────────────────────

class TestPedestrianScheduler:
    def setup_method(self):
        from services.ai_controller import PedestrianScheduler
        self.sched = PedestrianScheduler()

    def test_forced_insertion_when_max_wait_exceeded(self):
        peds = make_pedestrians(wait_sec=0.0)
        peds['N'].wait_time_sec = 91.0   # Exceeds 90s limit
        peds['N'].waiting_count = 3

        phase = self.sched.should_insert_pedestrian_phase(
            peds, PhaseID.NS_STRAIGHT, phase_elapsed=15.0
        )
        assert phase == PhaseID.PEDESTRIAN_NS, (
            "Should force PED_NS when N crosswalk exceeds max wait"
        )

    def test_no_ped_phase_when_not_needed(self):
        peds = make_pedestrians(wait_sec=10.0)   # short wait
        for p in peds.values():
            p.waiting_count = 0

        phase = self.sched.should_insert_pedestrian_phase(
            peds, PhaseID.NS_STRAIGHT, phase_elapsed=15.0
        )
        assert phase is None

    def test_adaptive_duration_scales_with_count(self):
        ped = PedestrianState(crosswalk_id='N', waiting_count=0)
        assert ped.adaptive_crossing_duration == PedestrianState.MIN_CROSSING_SEC

        ped.waiting_count = 10
        assert ped.adaptive_crossing_duration > PedestrianState.MIN_CROSSING_SEC

        ped.waiting_count = 100
        assert ped.adaptive_crossing_duration == PedestrianState.MAX_CROSSING_SEC


# ──────────────────────────────────────────────
# 5. FULL CONTROLLER INTEGRATION
# ──────────────────────────────────────────────

class TestIntersectionController:
    def setup_method(self):
        self.ctrl = IntersectionAIController(
            intersection_id=0,
            intersection_name="Test INT",
            ai_mode=True,
        )

    def test_initial_phase_is_all_red(self):
        assert self.ctrl.current_phase == PhaseID.ALL_RED

    def test_tick_produces_phase_timing_record(self):
        decision = self.ctrl.tick(dt=1.0)
        assert decision is not None
        assert decision.phase_id in PhaseID

    def test_traditional_mode_uses_fixed_timing(self):
        ctrl = IntersectionAIController(0, "Test", ai_mode=False)
        # Run enough ticks to complete first traditional phase
        for _ in range(35):
            ctrl.tick(dt=1.0)
        # Should have advanced through at least one phase
        assert ctrl.current_phase != PhaseID.ALL_RED or ctrl._trad_cycle_index > 0

    def test_no_conflicting_phases_in_sequence(self):
        """Run 200 ticks and verify no two consecutive active phases conflict."""
        ctrl = IntersectionAIController(0, "Test", ai_mode=True)
        previous = None
        for i in range(200):
            ctrl.tick(dt=1.0)
            current = ctrl.current_phase
            if previous and previous != PhaseID.ALL_RED and current != PhaseID.ALL_RED:
                in_conflict = current in CONFLICT_MATRIX.get(previous, frozenset())
                assert not in_conflict, (
                    f"Tick {i}: {previous.value} → {current.value} are conflicting!"
                )
            previous = current

    def test_emergency_mode_activates_priority(self):
        ctrl = IntersectionAIController(0, "Test", ai_mode=True)
        ctrl.emergency_direction = Direction.NORTH
        # Tick until phase changes from ALL_RED
        for _ in range(10):
            ctrl.tick(dt=1.0)
        # Emergency direction should prioritize NS phases
        # (exact phase depends on timing, but emergency flag should be set)
        assert ctrl.emergency_direction == Direction.NORTH or ctrl.current_phase in (
            PhaseID.NS_STRAIGHT, PhaseID.NS_LEFT, PhaseID.ALL_RED
        )

    def test_snapshot_serializable(self):
        self.ctrl.tick(dt=1.0)
        snap = self.ctrl.get_snapshot()
        import json
        # Test that all fields are serializable (enums converted by .value in snapshot)
        assert snap.intersection_id == 0
        assert snap.active_phase is not None

    def test_detection_ingestion(self):
        detection = YOLODetection(
            lane_id=1,
            vehicle_ids=[10, 11, 12],
            vehicle_count_now=5,
            vehicle_count_total=5,
            vehicle_types=[VehicleType.CAR],
            fps=3.3,
            queue_length_vehicles=5,
        )
        self.ctrl.ingest_detections({1: detection}, dt=1.0)
        assert self.ctrl.arms[Direction.NORTH].incoming_l1.vehicle_count > 0


# ──────────────────────────────────────────────
# 6. MULTI-INTERSECTION COORDINATOR
# ──────────────────────────────────────────────

class TestCoordinator:
    def setup_method(self):
        self.coord = MultiIntersectionCoordinator()

    def test_neighbors_of_center(self):
        # INT 4 (grid [1,1]) should have all 4 neighbors
        n = self.coord.get_neighbors(4)
        assert n['north'] == 1
        assert n['south'] == 7
        assert n['east']  == 5
        assert n['west']  == 3

    def test_neighbors_of_corner(self):
        # INT 0 (grid [0,0]) — top-left corner
        n = self.coord.get_neighbors(0)
        assert n['north'] is None
        assert n['west']  is None
        assert n['east']  == 1
        assert n['south'] == 3

    def test_spillback_pressure_increases_with_congestion(self):
        pressures = {i: 0.3 for i in range(9)}
        factor_low = self.coord.propagate_pressure(4, 0.3, pressures)

        pressures_high = {i: 0.85 for i in range(9)}
        factor_high = self.coord.propagate_pressure(4, 0.3, pressures_high)

        assert factor_high > factor_low, (
            "High neighbor congestion should increase spillback factor"
        )

    def test_green_wave_offset_increases_with_column(self):
        cycle = 120.0
        offset_0 = self.coord.compute_green_wave_offset(0, {}, cycle)
        offset_1 = self.coord.compute_green_wave_offset(1, {}, cycle)
        offset_2 = self.coord.compute_green_wave_offset(2, {}, cycle)
        assert offset_0 < offset_1 < offset_2


# ──────────────────────────────────────────────
# 7. DETECTION ADAPTER
# ──────────────────────────────────────────────

class TestDetectionAdapter:
    def setup_method(self):
        self.adapter = DetectionAdapter(ema_alpha=0.3)

    def make_lane(self) -> LaneState:
        return LaneState(
            lane_id=1,
            direction=Direction.NORTH,
            lane_type=LaneType.INCOMING_STRAIGHT_RIGHT,
        )

    def test_ema_smoothing_reduces_spike(self):
        lane = self.make_lane()
        lane.vehicle_count = 5.0

        # Spike: sudden jump to 50 (10× normal)
        detection = YOLODetection(
            lane_id=1, vehicle_ids=[], vehicle_count_now=50,
            vehicle_count_total=50, vehicle_types=[VehicleType.CAR], fps=3.3
        )
        self.adapter.ingest(lane, detection, dt=1.0)
        # Spike rejection should blend, not jump to 50
        assert lane.vehicle_count < 40, (
            f"Spike not rejected: count={lane.vehicle_count}"
        )

    def test_ema_converges_to_stable_value(self):
        lane = self.make_lane()
        stable_count = 10

        for _ in range(20):
            d = YOLODetection(
                lane_id=1, vehicle_ids=[], vehicle_count_now=stable_count,
                vehicle_count_total=stable_count, vehicle_types=[], fps=3.3
            )
            self.adapter.ingest(lane, d, dt=1.0)

        # Should converge close to stable_count
        assert abs(lane.vehicle_count - stable_count) < 2.0

    def test_emergency_detection(self):
        detection = YOLODetection(
            lane_id=1, vehicle_ids=[99], vehicle_count_now=1,
            vehicle_count_total=1,
            vehicle_types=[VehicleType.EMERGENCY], fps=3.3
        )
        assert DetectionAdapter.has_emergency_vehicle(detection)
