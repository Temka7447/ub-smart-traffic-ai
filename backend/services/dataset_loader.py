from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

REQUIRED_COLUMNS = {
    "timestamp", "intersection_id", "intersection_name", "district",
    "lane_id", "vehicle_count", "vehicle_type", "queue_length",
    "avg_speed", "inflow", "outflow", "weather", "signal_state",
    "congestion_index", "cycle_sec", "green_sec",
}

WEATHER_SPEED_FACTOR: dict[str, float] = {
    "Clear":  1.00,
    "Cloudy": 0.88,
    "Snow":   0.55,   # ← цасан шуурга: хурдыг илүү бууруулна
    "Fog":    0.50,   # ← манан: маш аюултай
    "Rain":   0.68,
    "Ice":    0.40,   # ← мөс: хамгийн аюултай
}

# Цаг агаарын ачааллын нэмэлт нөлөөлөл
WEATHER_QUEUE_MULTIPLIER: dict[str, float] = {
    "Clear":  1.00,
    "Cloudy": 1.10,
    "Snow":   1.55,   # ← цас: дараалал 55% нэмэгдэнэ
    "Fog":    1.45,
    "Rain":   1.35,
    "Ice":    1.70,   # ← мөс: дараалал 70% нэмэгдэнэ
}

LANE_TO_DIRECTION: dict[int, str] = {
    1: "north",
    2: "east",
    3: "south",
    4: "west",
}

# -----------------------------------------------------------------------
# Оргил цагийн тодорхойлолт — Монгол УБ хотын бодит цаг
# -----------------------------------------------------------------------
PEAK_HOURS = [
    (7, 9),    # өглөөний оргил
    (17, 20),  # оройн оргил
]

# Оргил ачааллын шалгуур — доод хязгаар
PEAK_CONGESTION_THRESHOLD    = 0.25   # ← бага утгаар илүү олон мөр орно
PEAK_QUEUE_THRESHOLD         = 3
PEAK_VEHICLE_COUNT_THRESHOLD = 3

# -----------------------------------------------------------------------
# Ачааллын нэмэгдүүлэх коэффициентүүд
# -----------------------------------------------------------------------

# Цагийн үржүүлэгч — оргил цаг дотор ч гэсэн хамгийн дээд цагийг ялгана
HOUR_LOAD_MULTIPLIER: dict[int, float] = {
    7:  1.60,
    8:  2.20,   # ← өглөөний хамгийн оргил
    9:  1.80,
    17: 1.70,
    18: 2.40,   # ← оройн хамгийн оргил
    19: 2.10,
    20: 1.50,
}

# Тээврийн хэрэгслийн ачааллын жин
VEHICLE_LOAD_WEIGHT: dict[str, float] = {
    "car":       1.0,
    "bus":       2.8,   # ← автобус: замыг их эзэлнэ
    "truck":     2.2,
    "emergency": 0.0,   # ← яаралтай тусламж: дарааллыг нэвтрэнэ
}

# Congestion index-ийн шатлал
CONGESTION_LOAD_MULTIPLIER: dict[str, float] = {
    "critical": 3.50,   # CI >= 0.80
    "heavy":    2.60,   # CI >= 0.65
    "moderate": 1.90,   # CI >= 0.45
    "light":    1.30,   # CI >= 0.25
    "free":     1.00,   # CI <  0.25
}

# Дарааллын уртаас хамаарах нэмэлт
QUEUE_OVERFLOW_THRESHOLD = 12   # >= 12 бол overflow нэмэлт
QUEUE_OVERFLOW_BONUS     = 1.40

# Орох/гарах урсгалын тэнцвэргүй байдал
INFLOW_OUTFLOW_IMBALANCE_THRESHOLD = 1.5   # inflow/outflow > 1.5 бол нэмэлт
IMBALANCE_MULTIPLIER               = 1.30


@dataclass
class LaneSnapshot:
    lane_id:          int
    direction:        str
    vehicle_count:    int
    vehicle_type:     str
    queue_length:     float
    avg_speed:        float
    inflow:           int
    outflow:          int
    signal_state:     str
    weather:          str
    congestion_index: float
    green_sec:        int
    cycle_sec:        int


@dataclass
class IntersectionSnapshot:
    timestamp:         pd.Timestamp
    intersection_id:   int
    intersection_name: str
    district:          str
    lanes:             list[LaneSnapshot] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Үндсэн property-үүд
    # ------------------------------------------------------------------
    @property
    def total_queue(self) -> int:
        return int(sum(ln.queue_length for ln in self.lanes))

    @property
    def direction_queues(self) -> dict[str, int]:
        result: dict[str, int] = {"north": 0, "south": 0, "east": 0, "west": 0}
        for lane in self.lanes:
            result[lane.direction] += int(lane.queue_length)
        return result

    @property
    def direction_vehicle_counts(self) -> dict[str, int]:
        result: dict[str, int] = {"north": 0, "south": 0, "east": 0, "west": 0}
        for lane in self.lanes:
            result[lane.direction] += lane.vehicle_count
        return result

    @property
    def weather(self) -> str:
        return self.lanes[0].weather if self.lanes else "Clear"

    @property
    def weather_speed_factor(self) -> float:
        return WEATHER_SPEED_FACTOR.get(self.weather, 1.0)

    @property
    def weather_queue_multiplier(self) -> float:
        return WEATHER_QUEUE_MULTIPLIER.get(self.weather, 1.0)

    @property
    def green_times(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for lane in self.lanes:
            result[lane.direction] = lane.green_sec
        return result

    @property
    def is_peak_hour(self) -> bool:
        hour = self.timestamp.hour
        return any(start <= hour <= end for start, end in PEAK_HOURS)

    @property
    def bus_directions(self) -> list[str]:
        return [ln.direction for ln in self.lanes if ln.vehicle_type == "bus"]

    @property
    def avg_congestion_index(self) -> float:
        if not self.lanes:
            return 0.0
        return sum(ln.congestion_index for ln in self.lanes) / len(self.lanes)

    @property
    def congestion_tier(self) -> str:
        ci = self.avg_congestion_index
        if ci >= 0.80:
            return "critical"
        if ci >= 0.65:
            return "heavy"
        if ci >= 0.45:
            return "moderate"
        if ci >= 0.25:
            return "light"
        return "free"

    @property
    def congestion_level(self) -> str:
        return self.congestion_tier

    @property
    def is_peak_load(self) -> bool:
        return (
            self.is_peak_hour
            and self.avg_congestion_index >= PEAK_CONGESTION_THRESHOLD
            and self.total_queue >= PEAK_QUEUE_THRESHOLD
            and sum(self.direction_vehicle_counts.values()) >= PEAK_VEHICLE_COUNT_THRESHOLD
        )

    # ------------------------------------------------------------------
    # Ачааллын нэмэгдүүлэх тооцоо
    # ------------------------------------------------------------------
    @property
    def hour_load_multiplier(self) -> float:
        return HOUR_LOAD_MULTIPLIER.get(self.timestamp.hour, 1.0)

    @property
    def congestion_load_multiplier(self) -> float:
        return CONGESTION_LOAD_MULTIPLIER.get(self.congestion_tier, 1.0)

    @property
    def inflow_outflow_multiplier(self) -> float:
        """Орох > гарах бол дараалал нэмэгдэнэ"""
        total_in  = sum(ln.inflow  for ln in self.lanes)
        total_out = sum(ln.outflow for ln in self.lanes)
        if total_out < 1:
            return IMBALANCE_MULTIPLIER
        ratio = total_in / total_out
        if ratio > INFLOW_OUTFLOW_IMBALANCE_THRESHOLD:
            return IMBALANCE_MULTIPLIER
        return 1.0

    @property
    def queue_overflow_multiplier(self) -> float:
        return QUEUE_OVERFLOW_BONUS if self.total_queue >= QUEUE_OVERFLOW_THRESHOLD else 1.0

    @property
    def vehicle_weight_multiplier(self) -> float:
        """Тээврийн хэрэгслийн төрлөөр жигнэсэн нэмэлт"""
        if not self.lanes:
            return 1.0
        total_weight = sum(
            ln.vehicle_count * VEHICLE_LOAD_WEIGHT.get(ln.vehicle_type, 1.0)
            for ln in self.lanes
        )
        total_count = sum(ln.vehicle_count for ln in self.lanes) or 1
        avg_weight = total_weight / total_count
        # 1.0 → 1.8 хооронд нормалчилна
        return min(1.8, max(1.0, avg_weight))

    def compute_amplified_queues(self) -> dict[str, int]:
        """
        Бүх хүчин зүйлийг нэгтгэн дарааллын уртыг
        маш ихээр нэмэгдүүлнэ.

        Томьёо:
          amplified = base_queue
            × hour_multiplier
            × congestion_multiplier
            × weather_queue_multiplier
            × inflow_outflow_multiplier
            × queue_overflow_multiplier
            × vehicle_weight_multiplier
        """
        base   = self.direction_queues
        factor = (
            self.hour_load_multiplier
            * self.congestion_load_multiplier
            * self.weather_queue_multiplier
            * self.inflow_outflow_multiplier
            * self.queue_overflow_multiplier
            * self.vehicle_weight_multiplier
        )
        return {
            direction: min(120, max(1, int(q * factor)))
            for direction, q in base.items()
        }

    def compute_amplified_arrival_rate(self) -> float:
        """Симуляторын arrival rate-ийг нэмэгдүүлнэ (0.0–0.99)"""
        base_rate = 0.55 if self.is_peak_hour else 0.30
        factor = (
            self.hour_load_multiplier
            * self.congestion_load_multiplier
            * self.inflow_outflow_multiplier
        )
        return min(0.99, base_rate * factor)

    def compute_amplified_spawn_chance(self) -> float:
        """Машин үүсгэх магадлалыг нэмэгдүүлнэ"""
        base = 0.78 if self.is_peak_hour else 0.45
        return min(0.99, base * self.hour_load_multiplier)

    def compute_reduced_green_times(self) -> dict[str, int]:
        """
        Оргил цагт ногоон гэрлийн хугацааг бууруулна
        (дараалал нэмэгдэх тусам богино хугацаа → илүү эргэлт)
        """
        base = self.green_times
        reduction = max(0.55, 1.0 - (self.avg_congestion_index * 0.5))
        return {
            d: max(10, int(t * reduction))
            for d, t in base.items()
        }

    def get_load_factors(self) -> dict[str, float]:
        """Дибаг / API-д харуулах бүх хүчин зүйлс"""
        return {
            "hour_load_multiplier":        round(self.hour_load_multiplier, 3),
            "congestion_load_multiplier":  round(self.congestion_load_multiplier, 3),
            "weather_queue_multiplier":    round(self.weather_queue_multiplier, 3),
            "inflow_outflow_multiplier":   round(self.inflow_outflow_multiplier, 3),
            "queue_overflow_multiplier":   round(self.queue_overflow_multiplier, 3),
            "vehicle_weight_multiplier":   round(self.vehicle_weight_multiplier, 3),
            "combined_factor":             round(
                self.hour_load_multiplier
                * self.congestion_load_multiplier
                * self.weather_queue_multiplier
                * self.inflow_outflow_multiplier
                * self.queue_overflow_multiplier
                * self.vehicle_weight_multiplier,
                3,
            ),
        }

    def to_simulator_state(self) -> dict[str, Any]:
        return {
            "queues":               self.direction_queues,
            "vehicle_counts":       self.direction_vehicle_counts,
            "green_times":          self.green_times,
            "is_peak_hour":         self.is_peak_hour,
            "is_peak_load":         self.is_peak_load,
            "bus_directions":       self.bus_directions,
            "weather":              self.weather,
            "weather_speed_factor": self.weather_speed_factor,
            "congestion_level":     self.congestion_level,
            "congestion_tier":      self.congestion_tier,
            "avg_congestion_index": round(self.avg_congestion_index, 3),
            "intersection_name":    self.intersection_name,
            "district":             self.district,
            "timestamp":            str(self.timestamp),
            "load_factors":         self.get_load_factors(),
        }


# ---------------------------------------------------------------------------
# Гол ачаалагч класс
# ---------------------------------------------------------------------------
class UBTrafficDatasetLoader:

    def __init__(self, filepath: str | Path) -> None:
        self.filepath = Path(filepath)
        self._df: pd.DataFrame | None = None

    def load(self) -> "UBTrafficDatasetLoader":
        if not self.filepath.exists():
            raise FileNotFoundError(f"Датасет олдсонгүй: {self.filepath}")

        ext = self.filepath.suffix.lower()
        if ext in (".xlsx", ".xls"):
            self._df = pd.read_excel(self.filepath, engine="openpyxl")
        elif ext == ".csv":
            self._df = pd.read_csv(self.filepath)
        else:
            raise ValueError(f"Дэмжигдэхгүй формат: {ext}")

        self._normalize_columns()
        self._validate()
        self._cast_types()

        total  = len(self._df)
        peak_n = len(self._df[self._is_peak_mask(self._df)])
        print(
            f"[loader] Нийт: {total:,} мөр | "
            f"Оргил ачаалал: {peak_n:,} мөр ({peak_n/max(1,total)*100:.1f}%)"
        )
        return self

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            raise RuntimeError("load() дуудаагүй байна.")
        return self._df

    @property
    def intersection_ids(self) -> list[int]:
        return sorted(self.df["intersection_id"].unique().tolist())

    def get_intersection_names(self) -> dict[int, str]:
        return (
            self.df[["intersection_id", "intersection_name"]]
            .drop_duplicates()
            .set_index("intersection_id")["intersection_name"]
            .to_dict()
        )

    # ------------------------------------------------------------------
    # Оргил ачааллын шүүлт
    # ------------------------------------------------------------------
    def _is_peak_mask(self, df: pd.DataFrame) -> pd.Series:
        hour      = df["timestamp"].dt.hour
        time_mask = pd.Series(False, index=df.index)
        for start, end in PEAK_HOURS:
            time_mask |= (hour >= start) & (hour <= end)
        return (
            time_mask
            & (df["congestion_index"] >= PEAK_CONGESTION_THRESHOLD)
            & (df["queue_length"]     >= PEAK_QUEUE_THRESHOLD)
            & (df["vehicle_count"]    >= PEAK_VEHICLE_COUNT_THRESHOLD)
        )

    @property
    def peak_load_df(self) -> pd.DataFrame:
        return self.df[self._is_peak_mask(self.df)].copy()

    @property
    def non_peak_df(self) -> pd.DataFrame:
        return self.df[~self._is_peak_mask(self.df)].copy()

    # ------------------------------------------------------------------
    # Snapshot авах
    # ------------------------------------------------------------------
    def get_snapshot(
        self, intersection_id: int, timestamp: pd.Timestamp | str
    ) -> IntersectionSnapshot | None:
        ts  = pd.Timestamp(timestamp)
        sub = self.df[self.df["intersection_id"] == intersection_id].copy()
        if sub.empty:
            return None
        sub["_diff"] = (sub["timestamp"] - ts).abs()
        closest_ts   = sub.loc[sub["_diff"].idxmin(), "timestamp"]
        return self._rows_to_snapshot(sub[sub["timestamp"] == closest_ts], closest_ts)

    def get_latest_snapshot(self, intersection_id: int) -> IntersectionSnapshot | None:
        sub = self.df[self.df["intersection_id"] == intersection_id]
        if sub.empty:
            return None
        ts = sub["timestamp"].max()
        return self._rows_to_snapshot(sub[sub["timestamp"] == ts], ts)

    def get_latest_peak_snapshot(self, intersection_id: int) -> IntersectionSnapshot | None:
        sub = self.peak_load_df[self.peak_load_df["intersection_id"] == intersection_id]
        if sub.empty:
            return None
        ts = sub["timestamp"].max()
        return self._rows_to_snapshot(sub[sub["timestamp"] == ts], ts)

    def get_heaviest_peak_snapshot(self, intersection_id: int) -> IntersectionSnapshot | None:
        """Хамгийн өндөр congestion_index-тэй оргил хэмжилт"""
        sub = self.peak_load_df[self.peak_load_df["intersection_id"] == intersection_id]
        if sub.empty:
            return None
        # Нийт дарааллын уртаар хамгийн их цагийг ол
        grouped = (
            sub.groupby("timestamp")["queue_length"]
            .sum()
            .reset_index()
        )
        heaviest_ts = grouped.loc[grouped["queue_length"].idxmax(), "timestamp"]
        rows = sub[sub["timestamp"] == heaviest_ts]
        return self._rows_to_snapshot(rows, pd.Timestamp(heaviest_ts))

    def get_all_snapshots_for_intersection(
        self, intersection_id: int, peak_only: bool = False
    ) -> list[IntersectionSnapshot]:
        src = self.peak_load_df if peak_only else self.df
        sub = src[src["intersection_id"] == intersection_id]
        return sorted(
            [self._rows_to_snapshot(g, pd.Timestamp(ts)) for ts, g in sub.groupby("timestamp")],
            key=lambda s: s.timestamp,
        )

    # ------------------------------------------------------------------
    # Симуляторт өгөх тохиргоо — АЧААЛЛЫГ МАШ ИХЭЭР НЭМЭГДҮҮЛСЭН
    # ------------------------------------------------------------------
    def get_simulator_config(
        self,
        intersection_id: int,
        use_peak_data: bool = False,
        use_heaviest: bool  = False,
    ) -> dict[str, Any]:
        """
        use_heaviest=True → хамгийн ачаалалтай хэмжилтийг авна
        use_peak_data=True → хамгийн сүүлийн оргил хэмжилтийг авна
        False → хамгийн сүүлийн хэмжилт

        Оргил үед бүх үзүүлэлтийг нэгтгэн нэмэгдүүлнэ.
        """
        if use_heaviest:
            snapshot = self.get_heaviest_peak_snapshot(intersection_id)
            if snapshot is None:
                snapshot = self.get_latest_peak_snapshot(intersection_id)
        elif use_peak_data:
            snapshot = self.get_latest_peak_snapshot(intersection_id)
        else:
            snapshot = self.get_latest_snapshot(intersection_id)

        if snapshot is None:
            return {}

        state = snapshot.to_simulator_state()

        if use_peak_data or use_heaviest:
            # Нэмэгдүүлсэн дараалал
            amplified_queues = snapshot.compute_amplified_queues()

            # Нэмэгдүүлсэн ногоон гэрэл (бага болгоно)
            reduced_green    = snapshot.compute_reduced_green_times()

            # Arrival rate & spawn chance
            arrival_rate  = snapshot.compute_amplified_arrival_rate()
            spawn_chance  = snapshot.compute_amplified_spawn_chance()

            state.update({
                "queues":             amplified_queues,
                "initial_queues":     amplified_queues,
                "green_times":        reduced_green,
                "peak_hour":          True,
                "peak_load_applied":  True,
                "arrival_rate":       round(arrival_rate, 3),
                "spawn_chance":       round(spawn_chance, 3),
                "max_vehicles":       120,            # ← маш их машин
                "discharge_rate":     4,              # ← нэг ногоон гэрэлд 4 машин гарна
                "load_factors":       snapshot.get_load_factors(),
                "congestion_tier":    snapshot.congestion_tier,
                "weather_factor":     snapshot.weather_speed_factor,
                "bus_directions":     snapshot.bus_directions,
            })
        else:
            state.update({
                "initial_queues":    snapshot.direction_queues,
                "peak_load_applied": False,
                "arrival_rate":      0.30,
                "spawn_chance":      0.45,
                "max_vehicles":      56,
                "discharge_rate":    2,
                "weather_factor":    snapshot.weather_speed_factor,
                "bus_directions":    snapshot.bus_directions,
            })

        return state

    def get_initial_queues_from_data(
        self, intersection_id: int, use_peak_data: bool = False
    ) -> dict[str, int]:
        cfg = self.get_simulator_config(intersection_id, use_peak_data)
        return cfg.get("initial_queues", {"north": 6, "south": 5, "east": 4, "west": 5})

    def get_green_times_from_data(self, intersection_id: int) -> dict[str, int]:
        s = self.get_latest_snapshot(intersection_id)
        return s.green_times if s else {"north": 30, "south": 30, "east": 30, "west": 30}

    def get_weather_speed_factor(self, intersection_id: int) -> float:
        s = self.get_latest_snapshot(intersection_id)
        return s.weather_speed_factor if s else 1.0

    # ------------------------------------------------------------------
    # Статистик
    # ------------------------------------------------------------------
    def summary_statistics(self) -> dict[str, Any]:
        df      = self.df
        peak_df = self.peak_load_df
        def _avg(f: pd.DataFrame, col: str) -> float:
            return round(float(f[col].mean()), 2) if not f.empty else 0.0
        return {
            "total_records":        len(df),
            "peak_load_records":    len(peak_df),
            "peak_load_pct":        round(len(peak_df) / max(1, len(df)) * 100, 1),
            "intersections":        df["intersection_id"].nunique(),
            "districts":            df["district"].nunique(),
            "time_range": {
                "start": str(df["timestamp"].min()),
                "end":   str(df["timestamp"].max()),
            },
            "vehicle_types":          df["vehicle_type"].value_counts().to_dict(),
            "weather_distribution":   df["weather"].value_counts().to_dict(),
            "avg_queue_length":       _avg(df,      "queue_length"),
            "peak_avg_queue":         _avg(peak_df, "queue_length"),
            "avg_speed_kmh":          _avg(df,      "avg_speed"),
            "peak_avg_speed_kmh":     _avg(peak_df, "avg_speed"),
            "avg_congestion_index":   _avg(df,      "congestion_index"),
            "peak_avg_congestion":    _avg(peak_df, "congestion_index"),
        }

    def congestion_by_hour(self) -> dict[int, float]:
        df = self.df.copy()
        df["hour"] = df["timestamp"].dt.hour
        return df.groupby("hour")["congestion_index"].mean().round(3).to_dict()

    def peak_congestion_by_hour(self) -> dict[int, float]:
        df = self.peak_load_df.copy()
        if df.empty:
            return {}
        df["hour"] = df["timestamp"].dt.hour
        return df.groupby("hour")["congestion_index"].mean().round(3).to_dict()

    def top_congested_intersections(self, n: int = 5) -> list[dict[str, Any]]:
        return (
            self.df
            .groupby(["intersection_id", "intersection_name", "district"])
            ["congestion_index"].mean().reset_index()
            .sort_values("congestion_index", ascending=False)
            .head(n)
            .to_dict(orient="records")
        )

    def weather_impact_analysis(self) -> dict[str, dict[str, float]]:
        return (
            self.df.groupby("weather")
            .agg(
                avg_speed=("avg_speed", "mean"),
                avg_congestion=("congestion_index", "mean"),
                avg_queue=("queue_length", "mean"),
            )
            .round(3).to_dict(orient="index")
        )

    def signal_efficiency(self) -> dict[str, Any]:
        df    = self.df
        green = df[df["signal_state"] == "green"]
        red   = df[df["signal_state"] == "red"]
        def _avg(f: pd.DataFrame, col: str) -> float:
            return round(float(f[col].mean()), 2) if not f.empty else 0.0
        return {
            "green_avg_outflow": _avg(green, "outflow"),
            "red_avg_outflow":   _avg(red,   "outflow"),
            "green_avg_speed":   _avg(green, "avg_speed"),
            "red_avg_speed":     _avg(red,   "avg_speed"),
            "green_avg_queue":   _avg(green, "queue_length"),
            "red_avg_queue":     _avg(red,   "queue_length"),
        }

    def peak_vs_normal_comparison(self) -> dict[str, Any]:
        p = self.peak_load_df
        n = self.non_peak_df
        def _avg(f: pd.DataFrame, col: str) -> float:
            return round(float(f[col].mean()), 2) if not f.empty else 0.0
        return {
            "peak": {
                "records":        len(p),
                "avg_queue":      _avg(p, "queue_length"),
                "avg_speed":      _avg(p, "avg_speed"),
                "avg_congestion": _avg(p, "congestion_index"),
                "avg_inflow":     _avg(p, "inflow"),
                "avg_outflow":    _avg(p, "outflow"),
            },
            "normal": {
                "records":        len(n),
                "avg_queue":      _avg(n, "queue_length"),
                "avg_speed":      _avg(n, "avg_speed"),
                "avg_congestion": _avg(n, "congestion_index"),
                "avg_inflow":     _avg(n, "inflow"),
                "avg_outflow":    _avg(n, "outflow"),
            },
        }

    # ------------------------------------------------------------------
    # Дотоод методууд
    # ------------------------------------------------------------------
    def _normalize_columns(self) -> None:
        self._df.columns = (
            self._df.columns.str.strip().str.lower()
            .str.replace(r"\s+", "_", regex=True)
        )

    def _validate(self) -> None:
        missing = REQUIRED_COLUMNS - set(self.df.columns)
        if missing:
            raise ValueError(f"Байхгүй баганууд: {missing}")

    def _cast_types(self) -> None:
        df = self._df
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        for col in ["intersection_id", "lane_id", "vehicle_count",
                    "inflow", "outflow", "cycle_sec", "green_sec"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        for col in ["queue_length", "avg_speed", "congestion_index"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        for col in ["intersection_name", "district", "vehicle_type",
                    "weather", "signal_state"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()
        df["weather"]      = df["weather"].str.capitalize()
        df["signal_state"] = df["signal_state"].str.lower()
        self._df = df

    def _rows_to_snapshot(
        self, rows: pd.DataFrame, timestamp: pd.Timestamp
    ) -> IntersectionSnapshot:
        first = rows.iloc[0]
        lanes = [
            LaneSnapshot(
                lane_id          = int(row["lane_id"]),
                direction        = LANE_TO_DIRECTION.get(int(row["lane_id"]), "north"),
                vehicle_count    = int(row["vehicle_count"]),
                vehicle_type     = str(row["vehicle_type"]),
                queue_length     = float(row["queue_length"]),
                avg_speed        = float(row["avg_speed"]),
                inflow           = int(row["inflow"]),
                outflow          = int(row["outflow"]),
                signal_state     = str(row["signal_state"]),
                weather          = str(row["weather"]),
                congestion_index = float(row["congestion_index"]),
                green_sec        = int(row["green_sec"]),
                cycle_sec        = int(row["cycle_sec"]),
            )
            for _, row in rows.iterrows()
        ]
        return IntersectionSnapshot(
            timestamp         = timestamp,
            intersection_id   = int(first["intersection_id"]),
            intersection_name = str(first["intersection_name"]),
            district          = str(first["district"]),
            lanes             = lanes,
        )