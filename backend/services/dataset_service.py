"""
Singleton wrapper — app дотор нэг ачаалагч ашиглана.
FastAPI lifespan дотор эхлүүлнэ.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.services.dataset_loader import UBTrafficDatasetLoader

_loader: UBTrafficDatasetLoader | None = None


def init_dataset(filepath: str | None = None) -> UBTrafficDatasetLoader:
    global _loader
    path = Path(filepath or os.getenv("UB_DATASET_PATH", "data/UB_Traffic_Dataset.xlsx"))
    _loader = UBTrafficDatasetLoader(path).load()
    print(f"[dataset] Ачааллаа: {len(_loader.df):,} мөр, "
          f"{_loader.df['intersection_id'].nunique()} уулзвар")
    return _loader


def get_loader() -> UBTrafficDatasetLoader:
    if _loader is None:
        raise RuntimeError("init_dataset() дуудагдаагүй байна.")
    return _loader


def get_dataset_state(intersection_id: int) -> dict[str, Any]:
    """Симуляторт шилжүүлэх тохиргоог буцаана."""
    return get_loader().get_simulator_config(intersection_id)