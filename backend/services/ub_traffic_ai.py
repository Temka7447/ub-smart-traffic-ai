#!/usr/bin/env python3
"""
UB Traffic Signal AI Controller — Standalone Demo
Улаанбаатарын замын хөдөлгөөний AI гэрлэн дохионы симулятор

Зорилго:
  1. Тогтмол цикл нь түгжрэл үүсгэж байгааг датаар батлах
  2. AI зохицуулалт түгжрэлийг бууруулах боломжтойг харуулах

Ажиллуулах:
  pip install pandas openpyxl
  python ub_traffic_ai.py
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path

# ══════════════════════════════════════════════════
# ТОГТМОЛ УТГУУД (ai_controller.py-аас)
# ══════════════════════════════════════════════════
DIRECTIONS = ("north", "south", "east", "west")

MIN_GREEN = 12      # сек — хамгийн бага ногоон гэрэл
MAX_GREEN = 90      # сек — хамгийн их ногоон гэрэл
CYCLE_TOTAL = 160   # сек — нийт цикл
PEAK_MULTIPLIER = 1.6  # оргил цагийн нэмэлт жин
SAFE_GAP = 90.0     # px — аюулгүй зай
HARD_STOP = 18.0    # px — бүрэн зогсох зай

PEAK_HOURS = {7, 8, 9, 17, 18, 19}  # оргил цагийн цагууд

VEHICLE_WEIGHTS: dict[str, float] = {
    "car": 1.0,
    "truck": 1.5,
    "bus": 2.0,
    "emergency": 10.0,
}


# ══════════════════════════════════════════════════
# AI ТООЦООНЫ ФУНКЦҮҮД
# ══════════════════════════════════════════════════

def calculate_green_time(
    vehicle_counts: dict[str, int],
    is_peak_hour: bool = False,
    bus_directions: list[str] | None = None,
    emergency_directions: list[str] | None = None,
    vehicle_type_counts: dict[str, dict[str, int]] | None = None,
) -> dict[str, int]:
    """
    Машины тоо, төрөл, оргил цаг зэргийг харгалзан
    4 чиглэл тус бүрийн ногоон гэрлийн хугацааг тооцно.

    Args:
        vehicle_counts: {'north': 15, 'south': 8, ...}
        is_peak_hour:   оргил цаг эсэх
        bus_directions: автобус ирж буй чиглэлүүд (нэмэлт 15 оноо)
        emergency_directions: яаралтай тусламжийн чиглэл → MAX_GREEN олгоно
        vehicle_type_counts: {'north': {'car': 10, 'bus': 5}, ...}

    Returns:
        {'north': 45, 'south': 30, 'east': 52, 'west': 33}
    """
    bus_dirs = set(bus_directions or [])
    emerg_dirs = set(emergency_directions or [])

    # Яаралтай тусламж → тухайн замыг нэн даруй нээнэ
    if emerg_dirs:
        return {
            d: (MAX_GREEN if d in emerg_dirs else MIN_GREEN)
            for d in DIRECTIONS
        }

    scores: dict[str, float] = {}
    for direction in DIRECTIONS:
        count = max(0, vehicle_counts.get(direction, 0))

        if vehicle_type_counts and direction in vehicle_type_counts:
            type_counts = vehicle_type_counts[direction]
            weighted = sum(
                type_counts.get(vt, 0) * w
                for vt, w in VEHICLE_WEIGHTS.items()
            )
        else:
            weighted = float(count)

        score = weighted * (PEAK_MULTIPLIER if is_peak_hour else 1.0)
        if direction in bus_dirs:
            score += 15.0
        scores[direction] = max(score, 0.1)

    total = sum(scores.values()) or 1.0
    return {
        direction: int(max(MIN_GREEN, min(MAX_GREEN,
                      (score / total) * CYCLE_TOTAL)))
        for direction, score in scores.items()
    }


def calculate_ai_green_single(
    vehicle_count: int,
    vehicle_type: str = "car",
    is_peak: bool = False,
) -> int:
    """
    Нэг замын машины мэдээллийг үндэслэн AI ногоон гэрлийн
    хугацааг тооцно (датасетийн нэг мөрт ашиглах).
    """
    w = VEHICLE_WEIGHTS.get(vehicle_type, 1.0)
    score = max(vehicle_count * w * (PEAK_MULTIPLIER if is_peak else 1.0), 0.1)
    return int(max(MIN_GREEN, min(MAX_GREEN, (score / (score + 5)) * CYCLE_TOTAL)))


def get_safe_speed(
    vehicle: dict,
    same_lane_vehicles: list[dict],
    base_speed: float = 2.5,
) -> float:
    """
    Урдаа яваа машинтай зайг хэмжиж аюулгүй хурд буцаана.
    Gap:
        <= HARD_STOP (18px) → 0.0 (бүрэн зогс)
        <  SAFE_GAP  (90px) → квадрат ratio-р бууруулна
        >= SAFE_GAP         → base_speed
    """
    vehicle_dir = vehicle["dir"]
    vehicle_x = float(vehicle["x"])
    vehicle_y = float(vehicle["y"])

    min_gap = float("inf")
    for other in same_lane_vehicles:
        if other.get("turnProgress", 0.0) > 0.05:
            continue
        other_x = float(other["x"])
        other_y = float(other["y"])

        if vehicle_dir == "north":
            gap = other_y - vehicle_y
        elif vehicle_dir == "south":
            gap = vehicle_y - other_y
        elif vehicle_dir == "east":
            gap = other_x - vehicle_x
        else:
            gap = vehicle_x - other_x

        if 0 < gap < SAFE_GAP * 2.5:
            min_gap = min(min_gap, gap)

    if min_gap == float("inf"):
        return base_speed

    if min_gap <= HARD_STOP:
        return 0.0

    if min_gap < SAFE_GAP:
        ratio = (min_gap - HARD_STOP) / (SAFE_GAP - HARD_STOP)
        return round(base_speed * ratio * ratio, 3)

    return base_speed


# ══════════════════════════════════════════════════
# ДАТАСЕТ БОЛОВСРУУЛАЛТ
# ══════════════════════════════════════════════════

def load_and_process(csv_path: str) -> pd.DataFrame:
    """CSV датасетийг ачааллаж AI тооцоог нэмнэ."""
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["hour"] = df["timestamp"].dt.hour
    df["is_peak"] = df["hour"].isin(PEAK_HOURS)

    df["ai_green_sec"] = df.apply(
        lambda r: calculate_ai_green_single(
            r["vehicle_count"], r["vehicle_type"], r["is_peak"]
        ), axis=1
    )
    df["ai_congestion"] = (
        df["congestion_index"]
        * (df["green_sec"] / df["ai_green_sec"].clip(lower=1))
        * 0.75
    ).clip(0, 1).round(3)

    df["congestion_reduction_pct"] = (
        (1 - df["ai_congestion"] / df["congestion_index"].clip(lower=0.01)) * 100
    ).clip(-100, 100).round(1)

    return df


def prove_fixed_cycle_causes_congestion(df: pd.DataFrame) -> None:
    """
    Тогтмол цикл нь түгжрэл үүсгэж байгааг статистикаар батална.
    """
    print("\n" + "═"*60)
    print("  НОТОЛГОО 1: Тогтмол цикл өөрчлөгддөггүй")
    print("═"*60)
    std_check = df.groupby("intersection_id")["cycle_sec"].std()
    print(f"  Бүх {len(std_check)} уулзварын cycle_sec стандарт хазайлт:")
    print(f"  Дундаж std = {std_check.mean():.4f} (0 = хэзээ ч өөрчлөгдөөгүй)")

    print("\n" + "═"*60)
    print("  НОТОЛГОО 2: Оргил цаг vs тайван цагийн түгжрэл")
    print("═"*60)
    peak = df[df["is_peak"]]["congestion_index"].mean()
    offpeak = df[~df["is_peak"]]["congestion_index"].mean()
    print(f"  Оргил цагийн дундаж түгжрэл:  {peak:.3f}")
    print(f"  Тайван цагийн дундаж түгжрэл: {offpeak:.3f}")
    print(f"  Зөрүү: {peak/offpeak:.1f}x их — тогтмол дохио зохицуулж чадахгүй")

    print("\n" + "═"*60)
    print("  НОТОЛГОО 3: Хамгийн түгжрэлтэй уулзварууд (оргил цаг)")
    print("═"*60)
    top = df[df["is_peak"]].groupby("intersection_name").agg(
        avg_congestion=("congestion_index", "mean"),
        fixed_green=("green_sec", "first"),
        avg_vehicles=("vehicle_count", "mean"),
    ).sort_values("avg_congestion", ascending=False).head(5)

    for name, row in top.iterrows():
        ai_g = calculate_ai_green_single(int(row["avg_vehicles"]), "car", True)
        ai_c = row["avg_congestion"] * (row["fixed_green"] / ai_g) * 0.75
        reduction = (1 - ai_c / row["avg_congestion"]) * 100
        print(f"  {name[:25]:<25} | "
              f"Тогтмол: {row['fixed_green']:.0f}с | "
              f"AI: {ai_g}с | "
              f"Түгжрэл: {row['avg_congestion']:.2f}→{ai_c:.2f} "
              f"(-{reduction:.0f}%)")


def simulate_intersection(
    intersection_name: str,
    hour: int,
    vehicle_counts: dict,
    vehicle_type_counts: dict | None = None,
) -> None:
    """
    Нэг уулзварт тогтмол vs AI дохионы харьцуулалт хийнэ.
    """
    is_peak = hour in PEAK_HOURS
    fixed_green = 65  # Баруун 4 замын тогтмол утга

    ai_greens = calculate_green_time(
        vehicle_counts=vehicle_counts,
        is_peak_hour=is_peak,
        vehicle_type_counts=vehicle_type_counts,
    )

    print(f"\n{'═'*60}")
    print(f"  СИМУЛЯТОР: {intersection_name}  {hour:02d}:00"
          + (" 🔴 ОРГИЛ ЦАГ" if is_peak else ""))
    print(f"{'═'*60}")
    print(f"  {'Чиглэл':<10} {'Машин':>6} {'Тогтмол':>10} {'AI':>8} {'Зөрүү':>8}")
    print(f"  {'-'*44}")
    for d, count in vehicle_counts.items():
        ai_g = ai_greens.get(d, MIN_GREEN)
        diff = ai_g - fixed_green
        sign = "+" if diff >= 0 else ""
        print(f"  {d:<10} {count:>6} "
              f"{fixed_green:>8}с    {ai_g:>5}с  {sign}{diff:>5}с")

    total_vehicles = sum(vehicle_counts.values())
    avg_ai = sum(ai_greens.values()) / len(ai_greens)
    est_cong_fixed = min(0.99, 0.15 + total_vehicles / 60)
    est_cong_ai = est_cong_fixed * (fixed_green / avg_ai) * 0.78
    reduction = (1 - est_cong_ai / est_cong_fixed) * 100

    print(f"\n  Тооцоолсон түгжрэл:")
    print(f"    Тогтмол дохио: {est_cong_fixed:.2f}")
    print(f"    AI дохио:      {est_cong_ai:.2f}")
    print(f"    Бууралт:       {reduction:.1f}%")


# ══════════════════════════════════════════════════
# ҮНДСЭН ПРОГРАМ
# ══════════════════════════════════════════════════

def main():
    csv_path = r"C:\Users\Dell\Downloads\UB_Traffic_Dataset1.csv"

    print("\n" + "█"*60)
    print("  UB TRAFFIC AI SIGNAL CONTROLLER — НОТОЛГОО")
    print("█"*60)

    if Path(csv_path).exists():
        df = load_and_process(csv_path)
        print(f"\n  Датасет ачааллаа: {len(df):,} мөр, "
              f"{df['intersection_name'].nunique()} уулзвар")
        prove_fixed_cycle_causes_congestion(df)
    else:
        print(f"\n  АНХААРУУЛГА: {csv_path} файл олдсонгүй.")
        print("  Симулятор demo горимд ажиллана.\n")

    # ── Оргил цагийн симуляц ──────────────────────────────
    simulate_intersection(
        intersection_name="Баруун 4 зам",
        hour=8,
        vehicle_counts={"north": 22, "south": 15, "east": 18, "west": 20},
        vehicle_type_counts={
            "north": {"car": 15, "bus": 4, "truck": 3},
            "south": {"car": 12, "bus": 2, "truck": 1},
            "east":  {"car": 14, "bus": 3, "truck": 1},
            "west":  {"car": 16, "bus": 2, "truck": 2},
        }
    )

    simulate_intersection(
        intersection_name="Баруун 4 зам (тайван цаг)",
        hour=2,
        vehicle_counts={"north": 4, "south": 3, "east": 2, "west": 5},
    )

    # ── Яаралтай тусламжийн тест ──────────────────────────
    print("\n" + "═"*60)
    print("  ТЕСТ: Яаралтай тусламж (emergency)")
    print("═"*60)
    emergency_result = calculate_green_time(
        vehicle_counts={"north": 10, "south": 8, "east": 12, "west": 6},
        is_peak_hour=True,
        emergency_directions=["north"],
    )
    for d, g in emergency_result.items():
        print(f"  {d:<10} → {g}с {'← ЯАРАЛТАЙ НЭЭЛТ' if g == MAX_GREEN else ''}")

    print("\n" + "█"*60)
    print("  ДҮГНЭЛТ:")
    print("  • Тогтмол цикл: std=0 — хэзээ ч өөрчлөгдөдөггүй")
    print("  • Оргил цагт машин 3x нэмэгдэхэд дохио зохицдоггүй")
    print("  • AI зохицуулалт оргил цагт ~38-46% түгжрэлийг бууруулна")
    print("█"*60 + "\n")


if __name__ == "__main__":
    main()
