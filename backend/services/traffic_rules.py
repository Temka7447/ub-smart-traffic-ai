"""
traffic_rules.py
================
Монгол Улсын Замын Хөдөлгөөний Дүрэм (2018 оны 239 дүгээр тогтоол)-ийн
үндсэн заалтуудыг симулятортой уялдуулсан зохицуулгын модуль.

Хэрэгжүүлсэн дүрмүүд:
  • 8.9  — Гэрлэн дохионы утга (ногоон/шар/улаан)
  • 8.18 — Хориглосон дохиогоор зогсох газар
  • 8.19 — Шар дохио асахад огцом тоормослохгүй аюулгүй үргэлжлүүлэх
  • 10.2 — Хөдөлгөөн эхлэхдээ бусадад зам тавьж өгөх
  • 10.9 — Зүүн тийш / буцаж эргэхдээ зам тавьж өгөх
  • 11.14 — Хөдөлгөөний хурдаас хамаарсан аюулгүй зай
  • 12.4 — Хурдны дээд хязгаар (суурин: 60, гадна: 80, тууш: 100 км/ц)
  • 12.5в — Хүүхэд тээвэрлэж яваа үед 50 км/ц-аас илүүгүй
  • 12.6г — Шалтгаангүй хэт удаан явахыг хориглоно
  • 13.2 — Гүйцэж түрүүлэхийг хориглох нөхцөлүүд
  • 14.8 — Түр зогсохыг хориглох газрууд
  • 15.8 — Адил замын уулзварт баруун гараас ирсэнд зам тавих
  • 15.9 — Гол/туслах замын уулзварт туслах замаас зам тавих
  • 16.1 — Явган зорчигчийн зохицуулдаггүй гарцад зам тавих
  • 4.4  — Онцгой тусгай дохиотой тээврийн хэрэгслийн давуу эрх
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

# ---------------------------------------------------------------------------
# Тогтмолууд — дүрмийн 12.4 заалт (км/ц → pixel/sec хөрвүүлэлт)
# Симулятор: PHYSICS_HZ=12, dynamics cruise ~30-48 pixel/sec
# 60 км/ц  ≈ 16.67 м/с → симуляторт ~42 pixel/sec (car cruise)
# ---------------------------------------------------------------------------
KMH_TO_PX_SEC = 42.0 / 60.0   # 0.7  px/sec per km/h  (тохируулгын коэффициент)

class ZoneType(Enum):
    """Замын бүс — 12.4, 12.5 заалт"""
    RESIDENTIAL   = auto()   # суурин газар: 60 км/ц
    RURAL         = auto()   # суурин газрын гадна: 80 км/ц
    HIGHWAY       = auto()   # тууш зам: 100 км/ц
    SCHOOL_ZONE   = auto()   # сургуулийн орчим / хороолол: 20 км/ц  (12.5д)
    DISTRICT      = auto()   # хороолол: 20 км/ц


SPEED_LIMITS: dict[ZoneType, float] = {
    ZoneType.RESIDENTIAL: 60.0,
    ZoneType.RURAL:       80.0,
    ZoneType.HIGHWAY:     100.0,
    ZoneType.SCHOOL_ZONE: 20.0,
    ZoneType.DISTRICT:    20.0,
}

# Тусгай тээврийн хэрэгслийн хурдны хязгаар (12.5 заалт)
SPEED_LIMIT_BUS_RESIDENTIAL   = 50.0   # 12.5а
SPEED_LIMIT_BUS_RURAL         = 70.0   # 12.5а
SPEED_LIMIT_BUS_HIGHWAY       = 80.0   # 12.5а
SPEED_LIMIT_CHILDREN          = 50.0   # 12.5в — хүүхэд тээвэрлэж яваа үед
SPEED_LIMIT_TOWING            = 40.0   # 12.5г — чирж яваа үед


class SignalPhase(Enum):
    """Гэрлэн дохионы төлөв — 8.9 заалт"""
    GREEN    = "green"       # 8.9а — хөдөлгөөн зөвшөөрөгдөнө
    YELLOW   = "yellow"      # 8.9б — дохио солигдохыг анхааруулна; зогсох
    ALL_RED  = "all_red"     # бүх чиглэл хориглогдоно
    RED      = "red"         # 8.9г — хөдөлгөөн хориглогдоно
    FLASHING = "flashing"    # 8.9в — зохицуулгагүй, болгоомжтой явах


class VehicleClass(Enum):
    """Тээврийн хэрэгслийн ангилал — 2.1 заалт"""
    A   = "motorcycle"        # мотоцикл
    B   = "car"               # суудлын автомашин
    C   = "truck"             # ачааны > 3500 кг
    D   = "bus"               # автобус
    M   = "tractor"           # трактор
    EMERGENCY = "emergency"   # онцгой (4.2 заалт)


@dataclass
class TrafficRuleContext:
    """
    Тээврийн хэрэгслийн одоогийн нөхцөл байдлыг агуулна.
    _move_vehicle дотор ашиглагдана.
    """
    vehicle_id:       int
    direction:        str                      # "north" | "south" | "east" | "west"
    vehicle_type:     str                      # "car" | "bus" | "truck" | "emergency"
    x:                float
    y:                float
    speed:            float                    # pixel/sec
    lane:             int
    turn:             str                      # "straight" | "left" | "right"
    turn_progress:    float

    # Симуляторын нөхцөл
    signal_phase:     str                      # SignalPhase.value
    active_dir:       str                      # "north" | "east"
    zone_type:        ZoneType = ZoneType.RESIDENTIAL

    # Тусгай нөхцөлүүд
    is_carrying_children: bool = False         # 12.5в
    is_towing:            bool = False         # 12.5г
    is_emergency:         bool = False         # 4.2 — тусгай дуут/гэрлэн дохио
    is_yielding:          bool = False
    waiting_ticks:        int  = 0             # хэчнээн frame хүлээсэн

    # Орчны мэдээлэл
    nearby_pedestrians:   list[dict] = field(default_factory=list)
    same_lane_vehicles:   list[dict] = field(default_factory=list)
    opposite_vehicles:    list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. Хурдны хязгаарын шалгалт — 12.4, 12.5, 12.6 заалт
# ---------------------------------------------------------------------------

def get_speed_limit_px_sec(ctx: TrafficRuleContext) -> float:
    """
    Дүрмийн 12.4, 12.5 заалтын дагуу тухайн тээврийн хэрэгслийн
    хурдны дээд хязгаарыг pixel/sec-ээр буцаана.

    12.6г — хэт удаан явах хориглолтыг хамтад нь шалгана.
    """
    # 4.2 — онцгой тусгай дохиотой тээврийн хэрэгсэлд хязгаарлалт хамаарахгүй
    if ctx.is_emergency:
        return 48.0 * KMH_TO_PX_SEC * (60.0 / 16.67)  # дотоод cruise pixel/sec

    # 12.5в — хүүхэд тээвэрлэж яваа үед 50 км/ц
    if ctx.is_carrying_children:
        return SPEED_LIMIT_CHILDREN * KMH_TO_PX_SEC

    # 12.5г — чирж яваа үед 40 км/ц
    if ctx.is_towing:
        return SPEED_LIMIT_TOWING * KMH_TO_PX_SEC

    # 12.5а — автобус/троллейбус
    if ctx.vehicle_type in ("bus",):
        limits = {
            ZoneType.RESIDENTIAL: SPEED_LIMIT_BUS_RESIDENTIAL,
            ZoneType.RURAL:       SPEED_LIMIT_BUS_RURAL,
            ZoneType.HIGHWAY:     SPEED_LIMIT_BUS_HIGHWAY,
            ZoneType.SCHOOL_ZONE: 20.0,
            ZoneType.DISTRICT:    20.0,
        }
        kmh = limits.get(ctx.zone_type, SPEED_LIMIT_BUS_RESIDENTIAL)
        return kmh * KMH_TO_PX_SEC

    # 12.4 — ерөнхий хурдны хязгаар
    kmh = SPEED_LIMITS.get(ctx.zone_type, 60.0)
    return kmh * KMH_TO_PX_SEC


def check_minimum_speed(ctx: TrafficRuleContext, dynamics_cruise: float) -> float:
    """
    12.6г — шалтгаангүй хэт удаан явахыг хориглоно.
    Хамгийн бага хурдыг cruise-н 15%-иар тооцно.
    Хориглосон газрын гадна байвал хамгийн бага хурдыг буцаана.
    """
    if ctx.turn_progress > 0:
        return 0.0   # эргэлтийн үед хязгаарлахгүй
    return dynamics_cruise * 0.15


# ---------------------------------------------------------------------------
# 2. Гэрлэн дохионы логик — 8.9, 8.18, 8.19 заалт
# ---------------------------------------------------------------------------

@dataclass
class SignalDecision:
    """Гэрлэн дохионы шийдвэр"""
    can_proceed:       bool    # хөдөлгөөн үргэлжлүүлж болно уу
    must_stop:         bool    # заавал зогсох ёстой уу
    safe_to_continue:  bool    # 8.19 — шар дохиогоор аюулгүй үргэлжлүүлж болох уу
    speed_limit_ratio: float   # хурдны харьцаа 0.0–1.0
    reason:            str


def evaluate_signal(
    ctx: TrafficRuleContext,
    stop_distance_px: float,
    current_speed: float,
    brake_decel: float,
) -> SignalDecision:
    """
    8.9, 8.18, 8.19 заалтын дагуу гэрлэн дохионы нөхцөлд ямар үйлдэл
    хийхийг тодорхойлно.

    stop_distance_px: зогсох шугам хүртэлх зай (pixel)
    current_speed:    одоогийн хурд (pixel/sec)
    brake_decel:      тоормосны хурдатгал (pixel/sec²)
    """
    # 4.2 — онцгой тээврийн хэрэгсэл дохио үл харгалзана
    if ctx.is_emergency:
        return SignalDecision(
            can_proceed=True, must_stop=False,
            safe_to_continue=True, speed_limit_ratio=1.0,
            reason="4.2: онцгой тусгай дохиотой — дохио үл харгалзана"
        )

    phase = ctx.signal_phase

    # 8.9а — ногоон: хөдөлгөөн зөвшөөрөгдөнө
    if phase == SignalPhase.GREEN.value:
        return SignalDecision(
            can_proceed=True, must_stop=False,
            safe_to_continue=True, speed_limit_ratio=1.0,
            reason="8.9а: ногоон дохио — хөдөлгөөн зөвшөөрөгдөнө"
        )

    # 8.9в — анивчсан шар: зохицуулгагүй, болгоомжтой явах
    if phase == SignalPhase.FLASHING.value:
        return SignalDecision(
            can_proceed=True, must_stop=False,
            safe_to_continue=True, speed_limit_ratio=0.6,
            reason="8.9в: анивчсан шар — болгоомжтой зорчино"
        )

    # 8.9б — шар дохио
    if phase == SignalPhase.YELLOW.value:
        # 8.18 — зогсох шугамын өмнө зогсох
        # 8.19 — огцом тоормослохгүйгээр зогсох боломжгүй бол үргэлжлүүлж болно
        stopping_dist = (current_speed ** 2) / (2.0 * max(brake_decel, 1.0))
        can_stop_safely = stopping_dist < stop_distance_px - 5.0

        if can_stop_safely:
            # Зогсох боломжтой → зогс
            ratio = max(0.0, min(1.0, (stop_distance_px - 4.0) / 58.0))
            ratio = ratio * ratio
            return SignalDecision(
                can_proceed=False, must_stop=True,
                safe_to_continue=False, speed_limit_ratio=ratio,
                reason="8.9б/8.18: шар дохио — зогсох шугамын өмнө зогсоно"
            )
        else:
            # 8.19 — огцом тоормослох боломжгүй → аюулгүй үргэлжлүүлнэ
            return SignalDecision(
                can_proceed=True, must_stop=False,
                safe_to_continue=True, speed_limit_ratio=0.8,
                reason="8.19: шар дохио гэхдээ огцом зогсох боломжгүй — үргэлжлүүлнэ"
            )

    # 8.9г / all_red — улаан дохио: хориглоно
    brake_ratio = max(0.0, min(1.0, (stop_distance_px - 4.0) / 58.0))
    return SignalDecision(
        can_proceed=False, must_stop=True,
        safe_to_continue=False,
        speed_limit_ratio=brake_ratio * brake_ratio,
        reason="8.9г/8.18: улаан дохио — зогсох шугамын өмнө зогсоно"
    )


# ---------------------------------------------------------------------------
# 3. Зам тавьж өгөх логик — 10.2, 10.9, 15.8, 15.9, 16.1 заалт
# ---------------------------------------------------------------------------

@dataclass
class YieldDecision:
    """Зам тавьж өгөх шийдвэр"""
    must_yield:        bool
    speed_ratio:       float   # 0.0 = бүрэн зогс, 1.0 = хурдаа барь
    reason:            str


def evaluate_yield(
    ctx: TrafficRuleContext,
    stop_distance_px: float,
    approaching_from_right: bool = False,
    is_main_road: bool = True,
    pedestrian_crossing: bool = False,
    pedestrian_in_crossing: bool = False,
) -> YieldDecision:
    """
    Дараах дүрмүүдийг шалгаж зам тавьж өгөх шаардлагыг тодорхойлно:

    10.2  — хөдөлгөөн эхлэхдээ бусадад зам тавьж өгнө
    10.9  — зүүн/буцаж эргэхдээ өөдөөс ирсэнд зам тавих
    15.8  — адил замын уулзварт баруун гараас ирсэнд зам тавих
    15.9  — туслах замаас яваа гол замаас ирсэнд зам тавих
    16.1  — явган зорчигчийн зохицуулдаггүй гарцад зам тавих
    4.4   — онцгой тусгай дохиотой тээврийн хэрэгсэлд зам тавих
    """
    # 4.4 — онцгой тээврийн хэрэгсэлд зам тавих (хамгийн өндөр зэрэглэл)
    if ctx.is_emergency:
        return YieldDecision(
            must_yield=False, speed_ratio=1.0,
            reason="4.4: онцгой тусгай дохиотой — давуу эрхтэй"
        )

    # 4.4 — орчинд онцгой тээврийн хэрэгсэл байвал бүрэн зам тавьж өгнө
    for other in ctx.same_lane_vehicles + ctx.opposite_vehicles:
        if other.get("type") == "emergency":
            ratio = max(0.0, min(1.0, (stop_distance_px - 4.0) / 80.0))
            return YieldDecision(
                must_yield=True, speed_ratio=ratio * ratio,
                reason="4.4: онцгой тусгай дохиотой тээврийн хэрэгсэлд зам тавьж өгнө"
            )

    # 16.1 — явган зорчигчийн зохицуулдаггүй гарцад зам тавих
    if pedestrian_crossing and pedestrian_in_crossing:
        ratio = max(0.0, min(1.0, (stop_distance_px - 4.0) / 70.0))
        return YieldDecision(
            must_yield=True, speed_ratio=ratio * ratio,
            reason="16.1: явган зорчигчийн зохицуулдаггүй гарцад зогсож зам тавьж өгнө"
        )

    # 15.9 — туслах замаас гол зам руу нэвтрэхдээ гол замын тээврийн хэрэгсэлд
    if not is_main_road:
        ratio = max(0.0, min(1.0, (stop_distance_px - 4.0) / 60.0))
        return YieldDecision(
            must_yield=True, speed_ratio=ratio * ratio,
            reason="15.9: туслах замаас гол замаар ирсэн тээврийн хэрэгсэлд зам тавьж өгнө"
        )

    # 15.8 — адил замын уулзварт баруун гараас ирсэнд зам тавих
    if approaching_from_right:
        ratio = max(0.0, min(1.0, (stop_distance_px - 4.0) / 55.0))
        return YieldDecision(
            must_yield=True, speed_ratio=ratio * ratio,
            reason="15.8: адил замын уулзварт баруун гараас ирсэн тээврийн хэрэгсэлд зам тавьж өгнө"
        )

    # 10.9 — зүүн тийш / буцаж эргэхдээ өөдөөс ирсэнд зам тавих
    if ctx.turn in ("left",):
        for other in ctx.opposite_vehicles:
            if other.get("turn", "straight") in ("straight", "right"):
                ratio = max(0.0, min(1.0, (stop_distance_px - 4.0) / 60.0))
                return YieldDecision(
                    must_yield=True, speed_ratio=ratio * ratio,
                    reason="10.9: зүүн тийш эргэхдээ өөдөөс чигээрээ яваа тээврийн хэрэгсэлд зам тавьж өгнө"
                )

    return YieldDecision(
        must_yield=False, speed_ratio=1.0,
        reason="зам тавьж өгөх шаардлагагүй"
    )


# ---------------------------------------------------------------------------
# 4. Гүйцэж түрүүлэх хориглолт — 13.2, 13.4 заалт
# ---------------------------------------------------------------------------

def can_overtake(
    ctx: TrafficRuleContext,
    at_intersection: bool = False,
    at_pedestrian_crossing: bool = False,
    in_school_zone: bool = False,
    at_railway: bool = False,
    on_bridge: bool = False,
    in_tunnel: bool = False,
    limited_visibility: bool = False,
    vehicle_ahead_is_overtaking: bool = False,
    vehicle_behind_is_overtaking: bool = False,
    front_vehicle_turning_left: bool = False,
    oncoming_danger: bool = False,
) -> tuple[bool, str]:
    """
    13.2, 13.4 заалтын дагуу гүйцэж түрүүлэх боломжтой эсэхийг шалгана.
    (bool, шалтгаан) хосыг буцаана.
    """
    # 13.2а — өөдөөс яваа тээврийн хэрэгслийн хөдөлгөөнд аюул учруулах
    if oncoming_danger:
        return False, "13.2а: өөдөөс яваа тээврийн хэрэгсэлд аюул учруулахаар байвал гүйцэж түрүүлэхийг хориглоно"

    # 13.2б — урд яваа тээврийн хэрэгсэл гүйцэж түрүүлж байгаа үед
    if vehicle_ahead_is_overtaking:
        return False, "13.2б: урд яваа тээврийн хэрэгсэл гүйцэж түрүүлэх үйлдэл хийж байгаа тохиолдолд хориглоно"

    # 13.2в — урд яваа тээврийн хэрэгсэл зүүн тийш дохио өгч байгаа үед
    if front_vehicle_turning_left:
        return False, "13.2в: урд яваа тээврийн хэрэгсэл зүүн гар тийш дохио өгч байгаа үед хориглоно"

    # 13.2г — араас яваа тээврийн хэрэгсэл гүйцэж түрүүлэхээр эхэлсэн үед
    if vehicle_behind_is_overtaking:
        return False, "13.2г: араас яваа тээврийн хэрэгсэл гүйцэж түрүүлэхээр үйлдэл эхэлсэн үед хориглоно"

    # 13.4а — уулзвар болон гарц дээр
    if at_intersection:
        return False, "13.4а: уулзвар болон гарц дээр гүйцэж түрүүлэхийг хориглоно"

    # 13.4б — явган хүний гарц дээр
    if at_pedestrian_crossing:
        return False, "13.4б: явган хүний гарц дээр гүйцэж түрүүлэхийг хориглоно"

    # 13.4в — хороолол болон сургуулийн орчимд
    if in_school_zone:
        return False, "13.4в: хороолол болон сургуулийн орчимд гүйцэж түрүүлэхийг хориглоно"

    # 13.4г — төмөр замын гарамд болон 100 м-ийн дотор
    if at_railway:
        return False, "13.4г: төмөр замын гарам дээр болон түүнд хүртэл 100 м-ийн дотор хориглоно"

    # 13.4д/е — гүүр болон хонгил
    if on_bridge or in_tunnel:
        return False, "13.4д/е: гүүрэн дээр болон хонгил дотор гүйцэж түрүүлэхийг хориглоно"

    # 13.4ж — үзэгдэлт хязгаарлагдмал хэсэгт
    if limited_visibility:
        return False, "13.4ж: үзэгдэлт хязгаарлагдмал хэсэгт гүйцэж түрүүлэхийг хориглоно"

    return True, "гүйцэж түрүүлэхийг зөвшөөрнө"


# ---------------------------------------------------------------------------
# 5. Аюулгүй зай — 11.14 заалт
# ---------------------------------------------------------------------------

def required_following_distance_px(speed_px_sec: float, vehicle_length_px: float = 20.0) -> float:
    """
    11.14 — хурдаас хамааран аюулгүй дагах зайг pixel-ээр тооцно.

    Физик томьёо: d = v * t_reaction + v²/(2*a)
    t_reaction ≈ 0.8 сек (жолоочийн хариу үйлдлийн хугацаа)
    a ≈ 70 px/sec² (дундаж тоормосны хурдатгал)
    """
    reaction_dist = speed_px_sec * 0.8
    braking_dist  = (speed_px_sec ** 2) / (2.0 * 70.0)
    safety_buffer = vehicle_length_px * 1.5   # машины биеийн 1.5 дахин
    return reaction_dist + braking_dist + safety_buffer


def get_following_speed_ratio(
    gap_to_leader_px: float,
    speed_px_sec: float,
    vehicle_length_px: float = 20.0,
) -> float:
    """
    11.14 заалтын дагуу урдаа яваа тээврийн хэрэгслээс шаардлагатай зайг
    барьж явах хурдны харьцааг (0.0–1.0) буцаана.
    """
    required_dist = required_following_distance_px(speed_px_sec, vehicle_length_px)
    hard_stop_dist = vehicle_length_px * 0.9

    if gap_to_leader_px <= hard_stop_dist:
        return 0.0

    if gap_to_leader_px < required_dist:
        ratio = (gap_to_leader_px - hard_stop_dist) / max(1.0, required_dist - hard_stop_dist)
        return round(max(0.0, min(1.0, ratio)), 3)

    return 1.0


# ---------------------------------------------------------------------------
# 6. Онцгой нөхцөлийн зан үйл — 4.2, 4.4 заалт
# ---------------------------------------------------------------------------

def handle_emergency_vehicle(
    ctx: TrafficRuleContext,
    emergency_direction: str,
    stop_distance_px: float,
) -> dict[str, Any]:
    """
    4.4 заалт — онцгой тусгай дуут болон гэрлэн дохио ажиллуулсан
    тээврийн хэрэгсэл ойртон ирж яваа үед бусад тээврийн хэрэгсэл
    зам тавьж өгөн чөлөөтэй зорчих боломжийг хангана.

    Буцаах: {"should_pull_over": bool, "speed_ratio": float, "reason": str}
    """
    if ctx.is_emergency:
        return {
            "should_pull_over": False,
            "speed_ratio": 1.0,
            "reason": "4.2: өөрөө онцгой тусгай дохиотой — давуу эрхтэй"
        }

    # Онцгой тээврийн хэрэгсэл ойртон ирж байна → зам тавьж өг
    ratio = max(0.0, min(1.0, (stop_distance_px - 4.0) / 80.0))
    return {
        "should_pull_over": True,
        "speed_ratio": ratio * ratio,
        "reason": "4.4: тусгай дуут болон гэрлэн дохио ажиллуулсан тээврийн хэрэгсэлд зам тавьж өгнө"
    }


# ---------------------------------------------------------------------------
# 7. Гол интеграцийн функц — _move_vehicle дотор дуудагдана
# ---------------------------------------------------------------------------

def apply_traffic_rules(
    vehicle: dict[str, Any],
    all_vehicles: list[dict[str, Any]],
    signal_state: str,
    active_dir: str,
    stop_distance_px: float,
    dynamics: dict[str, float],
    zone_type: ZoneType = ZoneType.RESIDENTIAL,
    at_intersection: bool = False,
    at_pedestrian_crossing: bool = False,
    pedestrian_in_crossing: bool = False,
    in_school_zone: bool = False,
    emergency_directions: list[str] | None = None,
    is_carrying_children: bool = False,
    is_towing: bool = False,
    approaching_from_right: bool = False,
    is_main_road: bool = True,
) -> dict[str, Any]:
    """
    Монгол Улсын Замын Хөдөлгөөний Дүрмийн зохицуулгын бүх шалгалтыг
    нэгтгэн target_speed болон waiting төлвийг буцаана.

    Буцаах утга:
    {
        "target_speed":   float,   # pixel/sec
        "waiting":        bool,
        "must_stop":      bool,
        "yield_reason":   str,
        "signal_reason":  str,
        "overtake_ok":    bool,
        "applied_rules":  list[str],
    }
    """
    direction    = vehicle["dir"]
    vehicle_type = vehicle.get("type", "car")
    x            = float(vehicle["x"])
    y            = float(vehicle["y"])
    speed        = float(vehicle.get("speed", 0.0))
    turn         = vehicle.get("turn", "straight")
    turn_prog    = float(vehicle.get("turnProgress", 0.0))

    is_emergency = vehicle_type == "emergency"
    emerg_dirs   = set(emergency_directions or [])

    # Ойрын замын онцгой тээврийн хэрэгсэл байгаа эсэх
    has_nearby_emergency = any(
        v.get("type") == "emergency"
        for v in all_vehicles
        if v["id"] != vehicle["id"]
    )

    # Нэг lane дахь тээврийн хэрэгслүүд
    same_lane = [
        v for v in all_vehicles
        if v["id"] != vehicle["id"]
        and v["dir"] == direction
        and v.get("lane") == vehicle.get("lane")
    ]

    # Эсрэг чигийн тээврийн хэрэгслүүд
    opp_dir_map = {"north": "south", "south": "north", "east": "west", "west": "east"}
    opposite = [
        v for v in all_vehicles
        if v["id"] != vehicle["id"]
        and v["dir"] == opp_dir_map.get(direction, "")
    ]

    ctx = TrafficRuleContext(
        vehicle_id=vehicle["id"],
        direction=direction,
        vehicle_type=vehicle_type,
        x=x, y=y,
        speed=speed,
        lane=vehicle.get("lane", 0),
        turn=turn,
        turn_progress=turn_prog,
        signal_phase=signal_state,
        active_dir=active_dir,
        zone_type=zone_type,
        is_carrying_children=is_carrying_children,
        is_towing=is_towing,
        is_emergency=is_emergency,
        nearby_pedestrians=[],
        same_lane_vehicles=same_lane,
        opposite_vehicles=opposite,
    )

    applied_rules: list[str] = []
    target_speed  = dynamics["cruise"]
    waiting       = False
    must_stop     = False
    yield_reason  = ""
    signal_reason = ""

    # -----------------------------------------------------------------------
    # A. Дүрэм 4.4 — ойрын онцгой тээврийн хэрэгсэлд зам тавьж өг
    # -----------------------------------------------------------------------
    if has_nearby_emergency and not is_emergency:
        emerg_action = handle_emergency_vehicle(ctx, direction, stop_distance_px)
        if emerg_action["should_pull_over"]:
            target_speed = min(target_speed, dynamics["cruise"] * emerg_action["speed_ratio"])
            waiting     = emerg_action["speed_ratio"] < 0.1
            applied_rules.append(emerg_action["reason"])

    # -----------------------------------------------------------------------
    # B. Дүрэм 12.4/12.5 — хурдны дээд хязгаар
    # -----------------------------------------------------------------------
    speed_limit = get_speed_limit_px_sec(ctx)
    if target_speed > speed_limit:
        target_speed = speed_limit
        applied_rules.append(f"12.4/12.5: хурдны хязгаар {speed_limit:.1f} px/sec")

    # -----------------------------------------------------------------------
    # C. Дүрэм 8.9/8.18/8.19 — гэрлэн дохионы логик
    # -----------------------------------------------------------------------
    phase_dirs = (
        ("north", "south") if active_dir in ("north", "south") else ("east", "west")
    )
    direction_has_green = (direction in phase_dirs)

    if not direction_has_green:
        signal_dec = evaluate_signal(ctx, stop_distance_px, speed, dynamics["brake"])
        signal_reason = signal_dec.reason
        if signal_dec.must_stop:
            target_speed = min(target_speed, dynamics["cruise"] * signal_dec.speed_limit_ratio)
            must_stop    = True
            waiting      = signal_dec.speed_limit_ratio < 0.05
            applied_rules.append(signal_reason)
        elif not signal_dec.can_proceed:
            target_speed = min(target_speed, dynamics["cruise"] * signal_dec.speed_limit_ratio)
            applied_rules.append(signal_reason)

    # -----------------------------------------------------------------------
    # D. Дүрэм 10.9/15.8/15.9/16.1 — зам тавьж өгөх
    # -----------------------------------------------------------------------
    yield_dec = evaluate_yield(
        ctx,
        stop_distance_px,
        approaching_from_right=approaching_from_right,
        is_main_road=is_main_road,
        pedestrian_crossing=at_pedestrian_crossing,
        pedestrian_in_crossing=pedestrian_in_crossing,
    )
    yield_reason = yield_dec.reason
    if yield_dec.must_yield:
        target_speed = min(target_speed, dynamics["cruise"] * yield_dec.speed_ratio)
        waiting      = yield_dec.speed_ratio < 0.05
        applied_rules.append(yield_reason)

    # -----------------------------------------------------------------------
    # E. Дүрэм 11.14 — аюулгүй дагах зай
    # -----------------------------------------------------------------------
    if same_lane:
        # Хамгийн ойрын урдаа яваа тээврийн хэрэгслийг ол
        min_gap = float("inf")
        for other in same_lane:
            if other.get("turnProgress", 0.0) > 0.05:
                continue
            ox, oy = float(other["x"]), float(other["y"])
            if direction == "north":
                gap = oy - y
            elif direction == "south":
                gap = y - oy
            elif direction == "east":
                gap = ox - x
            else:
                gap = x - ox
            if 0 < gap < 200.0:
                min_gap = min(min_gap, gap)

        if min_gap < float("inf"):
            follow_ratio = get_following_speed_ratio(min_gap, speed)
            target_speed = min(target_speed, dynamics["cruise"] * follow_ratio)
            if follow_ratio < 1.0:
                applied_rules.append(
                    f"11.14: аюулгүй дагах зай — gap={min_gap:.1f}px, ratio={follow_ratio:.2f}"
                )
            if follow_ratio < 0.05:
                waiting = True

    # -----------------------------------------------------------------------
    # F. Дүрэм 13.2/13.4 — гүйцэж түрүүлэх шалгалт
    # -----------------------------------------------------------------------
    overtake_ok, overtake_reason = can_overtake(
        ctx,
        at_intersection=at_intersection,
        at_pedestrian_crossing=at_pedestrian_crossing,
        in_school_zone=in_school_zone,
    )

    # Эцсийн баталгаа
    target_speed = max(0.0, min(target_speed, dynamics["cruise"]))

    return {
        "target_speed":  target_speed,
        "waiting":       waiting,
        "must_stop":     must_stop,
        "yield_reason":  yield_reason,
        "signal_reason": signal_reason,
        "overtake_ok":   overtake_ok,
        "applied_rules": applied_rules,
    }


# ---------------------------------------------------------------------------
# 8. Симулятортой уялдах туслах функцүүд
# ---------------------------------------------------------------------------

def get_zone_from_sim_mode(
    mode: str,
    in_school_zone: bool = False,
    in_district: bool = False,
) -> ZoneType:
    """Симуляторын горимоос замын бүс тодорхойлно."""
    if in_school_zone or in_district:
        return ZoneType.SCHOOL_ZONE
    if mode == "highway":
        return ZoneType.HIGHWAY
    if mode == "rural":
        return ZoneType.RURAL
    return ZoneType.RESIDENTIAL   # өгөгдмөл: суурин газар


def format_applied_rules(applied_rules: list[str]) -> str:
    """Дебаг хэрэглүүрийн тулд хэрэглэгдсэн дүрмүүдийг форматлана."""
    if not applied_rules:
        return "дүрмийн хязгаарлалтгүй"
    return " | ".join(applied_rules)


def log_rule_violation(
    vehicle_id: int,
    rule: str,
    details: str,
) -> dict[str, Any]:
    """
    Дүрэм зөрчлийн бүртгэл (KPI-д ашиглагдана).
    Симулятор дотор self.violations жагсаалтад нэмж болно.
    """
    return {
        "vehicle_id": vehicle_id,
        "rule":       rule,
        "details":    details,
    }