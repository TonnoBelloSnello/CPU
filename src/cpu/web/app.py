from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..simulation import (
    DEFAULT_MAX_CYCLES,
    SimulationError,
    prepare_simulation_cache,
    run_snapshot,
    stream_snapshot_events,
)
from ..simulation.emulator import (
    EmulationError,
    run_emulator_snapshot,
    stream_emulator_events,
)
from ..simulation.runner import _batched_pixel_events, assemble_program_image
from ..simulation.snapshot import Snapshot

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _warm_simulator_cache() -> None:
    try:
        prepare_simulation_cache(fast=True)
    except SimulationError:
        return


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    threading.Thread(
        target=_warm_simulator_cache,
        name="cpu-simulator-cache-warmer",
        daemon=True,
    ).start()
    yield


app = FastAPI(title="CPU Simulation Lab", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SimulationRequest(BaseModel):
    program: str = Field(..., min_length=1)
    mem_start: int = 0
    mem_end: int = 255
    key_mask: int = Field(default=0, ge=0, le=0xF)
    max_cycles: int = Field(default=DEFAULT_MAX_CYCLES, ge=1, le=10_000_000)
    engine: Literal["fast", "rtl"] = "rtl"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/simulate")
def simulate(request: SimulationRequest) -> Snapshot:
    program = request.program.strip()
    if not program:
        raise HTTPException(status_code=400, detail="Program cannot be empty")

    try:
        if request.engine == "fast":
            program_bytes, labels = assemble_program_image(program)
            return run_emulator_snapshot(
                program_bytes,
                labels=labels,
                mem_start=request.mem_start,
                mem_end=request.mem_end,
                key_mask=request.key_mask,
                max_cycles=request.max_cycles,
            )
        return run_snapshot(
            program_text=program,
            mem_start=request.mem_start,
            mem_end=request.mem_end,
            key_mask=request.key_mask,
            max_cycles=request.max_cycles,
        )
    except (SimulationError, EmulationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/simulate/stream")
def simulate_stream(request: SimulationRequest) -> StreamingResponse:
    program = request.program.strip()
    if not program:
        raise HTTPException(status_code=400, detail="Program cannot be empty")

    def ndjson_stream() -> Iterator[str]:
        events = None
        try:
            if request.engine == "fast":
                program_bytes, labels = assemble_program_image(program)
                events = _batched_pixel_events(
                    stream_emulator_events(
                        program_bytes,
                        labels=labels,
                        mem_start=request.mem_start,
                        mem_end=request.mem_end,
                        key_mask=request.key_mask,
                        max_cycles=request.max_cycles,
                    )
                )
            else:
                events = stream_snapshot_events(
                    program_text=program,
                    mem_start=request.mem_start,
                    mem_end=request.mem_end,
                    key_mask=request.key_mask,
                    max_cycles=request.max_cycles,
                    fast=True,
                )
            for event in events:
                if event["type"] == "start":
                    event = {
                        **event,
                        "engine": request.engine,
                        "cycle_accurate": request.engine == "rtl",
                    }
                yield json.dumps(event, separators=(",", ":")) + "\n"
        except (SimulationError, EmulationError) as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, separators=(",", ":")) + "\n"
            yield json.dumps({"type": "done"}, separators=(",", ":")) + "\n"
        finally:
            if events is not None:
                events.close()

    return StreamingResponse(ndjson_stream(), media_type="application/x-ndjson")
