from __future__ import annotations

import shutil

import pytest

from src.cpu.simulation.runner import stream_snapshot_events


def test_stream_snapshot_events_include_pixels_and_snapshot() -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")

    program = "\n".join(
        [
            "main:",
            "MOV R0, V1",
            "MOV R1, V2",
            "PIXEL R0, R1, V255",
        ]
    )

    events = list(stream_snapshot_events(program, mem_start=0, mem_end=8))
    event_types = [event["type"] for event in events]

    assert "start" in event_types
    assert "pixel" in event_types
    assert "snapshot" in event_types
    assert event_types[-1] == "done"


def test_stream_snapshot_deduplicates_repeated_pixel_writes() -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")

    program = "\n".join(
        [
            "main:",
            "MOV R0, V1",
            "MOV R1, V2",
            "PIXEL R0, R1, V255",
            "PIXEL R0, R1, V255",
            "PIXEL R0, R1, V255",
        ]
    )

    events = list(stream_snapshot_events(program, mem_start=0, mem_end=8))
    pixel_events = [event for event in events if event["type"] == "pixel"]

    assert len(pixel_events) == 1


def test_stream_snapshot_pixelnb_drains_before_halt_snapshot() -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")

    program = "\n".join(
        [
            "main:",
            "MOV R1, V2",
            "MOV R0, V1",
            "PIXELNB R0, R1, V10",
            "ADD R0, R0, V1",
            "PIXELNB R0, R1, V20",
            "ADD R0, R0, V1",
            "PIXELNB R0, R1, V30",
        ]
    )

    events = list(stream_snapshot_events(program, mem_start=0, mem_end=8))
    snapshots = [event for event in events if event["type"] == "snapshot"]
    assert len(snapshots) == 1

    framebuffer = snapshots[0]["framebuffer"]
    framebuffer_map = {entry["addr"]: entry["dec"] for entry in framebuffer}

    assert framebuffer_map[321] == 10
    assert framebuffer_map[322] == 20
    assert framebuffer_map[323] == 30
