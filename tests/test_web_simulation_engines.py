from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.cpu.simulation.snapshot import StreamEvent
from src.cpu.web.app import SimulationRequest, simulate, simulate_stream


async def _collect_stream(request: SimulationRequest) -> list[StreamEvent]:
    response = simulate_stream(request)
    events: list[StreamEvent] = []
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else bytes(chunk).decode()
        events.extend(json.loads(line) for line in text.splitlines() if line)
    return events


@pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not available on PATH",
)
def test_fast_web_engine_matches_rtl_snapshot_and_batches_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CPU_SIM_CACHE_DIR", str(tmp_path / "cache"))
    program = """space:
        value = 00000000
    main:
        MOV R0,V11
        ADD R1,R0,V7
        SAVEM R1,[value]
        MOVM R2,[value]
        FMOV R3,F3.0
        FDIV R4,R3,F2.0
        MOV R5,V4
        MOV R6,V6
        PIXELNB R5,R6,V10
        PIXEL R5,R6,V20
    """

    fast, rtl = (
        asyncio.run(
            _collect_stream(
                SimulationRequest(
                    program=program,
                    mem_start=0,
                    mem_end=8,
                    engine=engine,
                )
            )
        )
        for engine in ("fast", "rtl")
    )

    assert fast[0]["type"] == "start"
    assert rtl[0]["type"] == "start"
    assert fast[0]["engine"] == "fast"
    assert fast[0]["cycle_accurate"] is False
    assert rtl[0]["engine"] == "rtl"
    assert rtl[0]["cycle_accurate"] is True
    assert any(event["type"] == "pixels" for event in fast)
    assert any(event["type"] == "pixels" for event in rtl)

    fast_snapshot = next(event for event in fast if event["type"] == "snapshot")
    rtl_snapshot = next(event for event in rtl if event["type"] == "snapshot")
    for field in ("registers", "memory", "framebuffer", "labels"):
        assert fast_snapshot[field] == rtl_snapshot[field]
    assert fast[-1] == rtl[-1] == {"type": "done"}


def test_json_api_remains_rtl_by_default() -> None:
    assert SimulationRequest(program="main:\n MOV R0,V1").engine == "rtl"


def test_fast_engine_reports_assembly_errors_instead_of_http_500() -> None:
    request = SimulationRequest(program="main:\n MOV R0,Vbogus", engine="fast")
    with pytest.raises(HTTPException) as exc_info:
        simulate(request)
    assert exc_info.value.status_code == 400
    assert "Assembly failed" in str(exc_info.value.detail)

    events = asyncio.run(_collect_stream(request))
    assert events[0]["type"] == "error"
    assert "Assembly failed" in str(events[0]["message"])
    assert events[-1] == {"type": "done"}


def test_fast_stream_flushes_pixels_before_timeout_error() -> None:
    request = SimulationRequest(
        program="""main:
            MOV R0,V1
            MOV R1,V2
            PIXEL R0,R1,V7
            WAITK R3,V1
        """,
        max_cycles=25,
        engine="fast",
    )

    events = asyncio.run(_collect_stream(request))

    assert [event["type"] for event in events] == ["start", "pixels", "error", "done"]
    assert events[1] == {"type": "pixels", "pixels": [[321, 7]]}
    assert events[2]["type"] == "error"
    assert "max_cycles=25" in events[2]["message"]
