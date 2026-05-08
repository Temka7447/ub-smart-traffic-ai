from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import analytics, signals, simulation
from backend.services.simulator import TrafficSimulator


@asynccontextmanager
async def lifespan(app: FastAPI):
    simulator_service = TrafficSimulator()
    app.state.simulator = simulator_service
    await simulator_service.start_loop()
    try:
        yield
    finally:
        await simulator_service.stop_loop()


app = FastAPI(
    title="AI Traffic Signal Simulator API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
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
