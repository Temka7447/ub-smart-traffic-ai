from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import analytics, signals, simulation
from backend.routers.dataset import router as dataset_router
from backend.services.dataset_service import init_dataset
from backend.services.simulator import TrafficSimulator

from pathlib import Path


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Датасет ачаалах


    dataset_path = Path(__file__).parent / "data" / "UB_Traffic_Dataset1.csv"
    try:
        loader = init_dataset(dataset_path)
        app.state.dataset = loader
        print(f"[dataset] OK — {len(loader.df):,} мөр ачааллаа")
    except FileNotFoundError:
        print(f"[dataset] WARN: файл олдсонгүй → {dataset_path}")
        app.state.dataset = None
    except Exception as e:
        print(f"[dataset] ERROR: {e}")
        app.state.dataset = None

    # 2. Симулятор эхлүүлэх
    simulator_service = TrafficSimulator()
    app.state.simulator = simulator_service
    await simulator_service.start_loop()
    try:
        yield
    finally:
        await simulator_service.stop_loop()


app = FastAPI(
    title="AI Traffic Signal Simulator API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(signals.router)
app.include_router(simulation.router)
app.include_router(simulation.ws_router)
app.include_router(analytics.router)
app.include_router(dataset_router)