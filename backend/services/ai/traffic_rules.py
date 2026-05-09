"""
Traffic Rules Engine — Conflict Matrix & Phase Safety
======================================================
Enforces real-world traffic engineering constraints.
No phase can be activated that conflicts with an already-active phase.
This is the safety layer that the AI optimizer CANNOT override.

Conflict logic:
 - Opposite straight flows (NS vs EW) conflict: crossing paths
 - Left turns conflict with opposing straight and crossing pedestrians
 - Pedestrian phases conflict with all vehicle movements in that axis
 - All-red is always conflict-free (safety buffer)

Reference: HCM (Highway Capacity Manual) Chapter 19 — Signalized Intersections
"""

from __future__ import annotations
from typing import FrozenSet
from .lane_state import PhaseID, Direction, SignalState


# ──────────────────────────────────────────────
# CONFLICT MATRIX
# Each entry: set of phases that CANNOT run simultaneously with the key phase.
# This is symmetrical: if A conflicts with B, B conflicts with A.
# ──────────────────────────────────────────────

CONFLICT_MATRIX: dict[PhaseID, FrozenSet[PhaseID]] = {

    # N/S straight + right — conflicts with E/W movement and N/S ped crossings
    PhaseID.NS_STRAIGHT: frozenset([
        PhaseID.EW_STRAIGHT,
        PhaseID.EW_LEFT,
        PhaseID.NS_LEFT,       # N straight + S left = head-on left conflict
        PhaseID.PEDESTRIAN_NS, # peds crossing N/S streets conflict with NS vehicles
        PhaseID.PEDESTRIAN_EW, # peds crossing E/W streets conflict with NS vehicles
    ]),

    # N/S protected left — conflicts with everything except own pedestrian cycle
    PhaseID.NS_LEFT: frozenset([
        PhaseID.NS_STRAIGHT,   # can't have left + straight from same axis simultaneously
        PhaseID.EW_STRAIGHT,
        PhaseID.EW_LEFT,
        PhaseID.PEDESTRIAN_NS,
        PhaseID.PEDESTRIAN_EW,
    ]),

    # E/W straight + right
    PhaseID.EW_STRAIGHT: frozenset([
        PhaseID.NS_STRAIGHT,
        PhaseID.NS_LEFT,
        PhaseID.EW_LEFT,
        PhaseID.PEDESTRIAN_NS,
        PhaseID.PEDESTRIAN_EW,
    ]),

    # E/W protected left
    PhaseID.EW_LEFT: frozenset([
        PhaseID.EW_STRAIGHT,
        PhaseID.NS_STRAIGHT,
        PhaseID.NS_LEFT,
        PhaseID.PEDESTRIAN_NS,
        PhaseID.PEDESTRIAN_EW,
    ]),

    # Pedestrian NS crosswalk (pedestrians crossing the N/S road = walking E/W)
    # Conflicts with all vehicle phases that move through their path
    PhaseID.PEDESTRIAN_NS: frozenset([
        PhaseID.NS_STRAIGHT,
        PhaseID.NS_LEFT,
        PhaseID.EW_STRAIGHT,
        PhaseID.EW_LEFT,
        PhaseID.PEDESTRIAN_EW,  # only one ped phase at a time
    ]),

    # Pedestrian EW crosswalk
    PhaseID.PEDESTRIAN_EW: frozenset([
        PhaseID.NS_STRAIGHT,
        PhaseID.NS_LEFT,
        PhaseID.EW_STRAIGHT,
        PhaseID.EW_LEFT,
        PhaseID.PEDESTRIAN_NS,
    ]),

    # All-red: conflicts with nothing — always safe
    PhaseID.ALL_RED: frozenset(),
}


# ──────────────────────────────────────────────
# PHASE → SIGNAL STATE MAPPING
# Which directions get green (or green arrow) for each phase.
# ──────────────────────────────────────────────

PHASE_SIGNALS: dict[PhaseID, dict[Direction, SignalState]] = {
    PhaseID.NS_STRAIGHT: {
        Direction.NORTH: SignalState.GREEN,
        Direction.SOUTH: SignalState.GREEN,
        Direction.EAST:  SignalState.RED,
        Direction.WEST:  SignalState.RED,
    },
    PhaseID.NS_LEFT: {
        Direction.NORTH: SignalState.GREEN_LEFT,
        Direction.SOUTH: SignalState.GREEN_LEFT,
        Direction.EAST:  SignalState.RED,
        Direction.WEST:  SignalState.RED,
    },
    PhaseID.EW_STRAIGHT: {
        Direction.NORTH: SignalState.RED,
        Direction.SOUTH: SignalState.RED,
        Direction.EAST:  SignalState.GREEN,
        Direction.WEST:  SignalState.GREEN,
    },
    PhaseID.EW_LEFT: {
        Direction.NORTH: SignalState.RED,
        Direction.SOUTH: SignalState.RED,
        Direction.EAST:  SignalState.GREEN_LEFT,
        Direction.WEST:  SignalState.GREEN_LEFT,
    },
    PhaseID.PEDESTRIAN_NS: {
        Direction.NORTH: SignalState.PEDESTRIAN,
        Direction.SOUTH: SignalState.PEDESTRIAN,
        Direction.EAST:  SignalState.RED,
        Direction.WEST:  SignalState.RED,
    },
    PhaseID.PEDESTRIAN_EW: {
        Direction.NORTH: SignalState.RED,
        Direction.SOUTH: SignalState.RED,
        Direction.EAST:  SignalState.PEDESTRIAN,
        Direction.WEST:  SignalState.PEDESTRIAN,
    },
    PhaseID.ALL_RED: {
        Direction.NORTH: SignalState.ALL_RED,
        Direction.SOUTH: SignalState.ALL_RED,
        Direction.EAST:  SignalState.ALL_RED,
        Direction.WEST:  SignalState.ALL_RED,
    },
}


# ──────────────────────────────────────────────
# PHASE SEQUENCE (valid transition order)
# The AI can reorder phases, but must always insert ALL_RED between
# any two incompatible consecutive phases.
# ──────────────────────────────────────────────

# Default fallback cycle (used in traditional mode)
DEFAULT_CYCLE_SEQUENCE: list[PhaseID] = [
    PhaseID.NS_STRAIGHT,
    PhaseID.ALL_RED,
    PhaseID.NS_LEFT,
    PhaseID.ALL_RED,
    PhaseID.EW_STRAIGHT,
    PhaseID.ALL_RED,
    PhaseID.EW_LEFT,
    PhaseID.ALL_RED,
    PhaseID.PEDESTRIAN_NS,
    PhaseID.ALL_RED,
    PhaseID.PEDESTRIAN_EW,
    PhaseID.ALL_RED,
]

# Traditional fixed timing (seconds) — based on UB dataset: cycle=120s, green=65s
TRADITIONAL_TIMING: dict[PhaseID, float] = {
    PhaseID.NS_STRAIGHT:  30.0,
    PhaseID.NS_LEFT:      10.0,
    PhaseID.EW_STRAIGHT:  30.0,
    PhaseID.EW_LEFT:      10.0,
    PhaseID.PEDESTRIAN_NS: 15.0,
    PhaseID.PEDESTRIAN_EW: 15.0,
    PhaseID.ALL_RED:       4.0,   # 4-second all-red safety buffer
}

# AI timing bounds (min/max green per phase type)
AI_TIMING_BOUNDS: dict[PhaseID, tuple[float, float]] = {
    PhaseID.NS_STRAIGHT:  (15.0, 70.0),
    PhaseID.NS_LEFT:      (8.0,  25.0),
    PhaseID.EW_STRAIGHT:  (15.0, 70.0),
    PhaseID.EW_LEFT:      (8.0,  25.0),
    PhaseID.PEDESTRIAN_NS: (12.0, 45.0),
    PhaseID.PEDESTRIAN_EW: (12.0, 45.0),
    PhaseID.ALL_RED:       (3.0,  5.0),   # always 3-5s, not AI-adjustable
}

# Maximum starvation time per phase (seconds since last served)
# AI MUST serve a phase within this window, regardless of pressure score
MAX_STARVATION_SEC: dict[PhaseID, float] = {
    PhaseID.NS_STRAIGHT:  120.0,
    PhaseID.NS_LEFT:      150.0,
    PhaseID.EW_STRAIGHT:  120.0,
    PhaseID.EW_LEFT:      150.0,
    PhaseID.PEDESTRIAN_NS: 90.0,   # pedestrian hard max from model
    PhaseID.PEDESTRIAN_EW: 90.0,
    PhaseID.ALL_RED:       999.0,
}


# ──────────────────────────────────────────────
# TRAFFIC RULES ENGINE
# ──────────────────────────────────────────────

class TrafficRulesEngine:
    """
    Stateless safety validator.
    All decisions from the AI controller MUST pass through validate_transition()
    before being applied. This ensures no conflicting greens ever occur.
    """

    @staticmethod
    def validate_transition(
        current_phase: PhaseID,
        proposed_phase: PhaseID,
        current_elapsed_sec: float,
    ) -> tuple[bool, str]:
        """
        Check if a phase transition is safe and legal.

        Returns:
            (is_valid, reason_string)
        """
        # Rule 1: Never skip all-red between incompatible phases
        if current_phase != PhaseID.ALL_RED and proposed_phase != PhaseID.ALL_RED:
            if proposed_phase in CONFLICT_MATRIX.get(current_phase, frozenset()):
                return False, (
                    f"CONFLICT: {current_phase.value} → {proposed_phase.value} "
                    f"requires ALL_RED transition"
                )

        # Rule 2: Must satisfy minimum green time before switching
        min_green = AI_TIMING_BOUNDS.get(current_phase, (10.0, 60.0))[0]
        if current_phase != PhaseID.ALL_RED and current_elapsed_sec < min_green:
            return False, (
                f"MIN_GREEN violation: {current_phase.value} only ran "
                f"{current_elapsed_sec:.1f}s, minimum is {min_green}s"
            )

        return True, "OK"

    @staticmethod
    def requires_all_red_between(phase_a: PhaseID, phase_b: PhaseID) -> bool:
        """True if an ALL_RED buffer must be inserted between phase_a and phase_b."""
        if phase_a == PhaseID.ALL_RED or phase_b == PhaseID.ALL_RED:
            return False
        return phase_b in CONFLICT_MATRIX.get(phase_a, frozenset())

    @staticmethod
    def get_signals_for_phase(phase: PhaseID) -> dict[Direction, SignalState]:
        """Returns the complete signal state map for a given phase."""
        return PHASE_SIGNALS.get(phase, PHASE_SIGNALS[PhaseID.ALL_RED])

    @staticmethod
    def is_outgoing_direction_for_phase(
        phase: PhaseID,
        outgoing_direction: Direction,
    ) -> bool:
        """
        Returns True if the outgoing lane of `outgoing_direction` will
        receive vehicles when `phase` is active.
        E.g., NS_STRAIGHT active → East and West outgoing lanes receive traffic.
        Used by anti-gridlock: suppress phase if its outgoing target is full.
        """
        outgoing_target_map: dict[PhaseID, list[Direction]] = {
            PhaseID.NS_STRAIGHT:  [Direction.EAST, Direction.WEST],
            PhaseID.NS_LEFT:      [Direction.EAST, Direction.WEST],
            PhaseID.EW_STRAIGHT:  [Direction.NORTH, Direction.SOUTH],
            PhaseID.EW_LEFT:      [Direction.NORTH, Direction.SOUTH],
            PhaseID.PEDESTRIAN_NS: [],
            PhaseID.PEDESTRIAN_EW: [],
            PhaseID.ALL_RED:       [],
        }
        return outgoing_direction in outgoing_target_map.get(phase, [])

    @staticmethod
    def yellow_duration_for_speed(approach_speed_kmh: float) -> float:
        """
        ITE formula: yellow = reaction_time + v / (2a + 2gG)
        Simplified for urban intersections (30-60 km/h):
        Returns seconds of yellow clearance needed.
        """
        reaction_time = 1.0   # seconds
        deceleration = 3.0    # m/s^2 (comfortable urban decel)
        v_ms = approach_speed_kmh / 3.6
        yellow = reaction_time + v_ms / (2 * deceleration)
        return round(min(5.0, max(3.0, yellow)), 1)
