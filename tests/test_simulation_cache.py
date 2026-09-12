from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.cpu.simulation import runner

pytestmark = pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not available on PATH",
)


def test_runtime_harness_is_compiled_once_for_different_programs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CPU_SIM_CACHE_DIR", str(tmp_path / "cache"))
    compile_count = 0
    real_run_command = runner._run_command

    def count_compiles(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        nonlocal compile_count
        compile_count += 1
        return real_run_command(args, cwd)

    monkeypatch.setattr(runner, "_run_command", count_compiles)
    first = runner.run_snapshot("main:\n MOV R0,V11", mem_start=0, mem_end=1)
    second = runner.run_snapshot("main:\n MOV R0,V22", mem_start=9, mem_end=9)

    assert first["registers"]["R0"]["dec"] == 11
    assert second["registers"]["R0"]["dec"] == 22
    assert second["memory"] == [{"addr": 9, "dec": 0, "hex": "00"}]
    assert compile_count == 1


def test_cached_harness_keeps_parallel_programs_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CPU_SIM_CACHE_DIR", str(tmp_path / "cache"))
    runner.prepare_simulation_cache(fast=False)

    def simulate(value: int) -> int | None:
        result = runner.run_snapshot(
            f"main:\n MOV R0,V{value}", mem_start=0, mem_end=0
        )
        return result["registers"]["R0"]["dec"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(executor.map(simulate, (11, 22, 33, 44)))

    assert values == [11, 22, 33, 44]


def test_cached_stream_preserves_keys_pixels_and_final_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CPU_SIM_CACHE_DIR", str(tmp_path / "cache"))
    program = """main:
        MOV R0,V1
        MOV R1,V2
        PIXEL R0,R1,V7
        WAITK R3,V1
        MOV R2,V99
    """

    events = list(
        runner.stream_snapshot_events(
            program,
            key_mask=1,
            mem_start=0,
            mem_end=4,
            max_cycles=10_000,
            fast=True,
        )
    )

    assert events[0]["type"] == "start"
    batches = [event for event in events if event["type"] == "pixels"]
    assert batches == [{"type": "pixels", "pixels": [[321, 7]]}]
    snapshot = next(event for event in events if event["type"] == "snapshot")
    assert snapshot["registers"]["R2"]["dec"] == 99
    assert events[-1] == {"type": "done"}


def test_cache_directory_errors_are_reported_as_simulation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CPU_SIM_CACHE_DIR", str(tmp_path / "cache"))

    def fail_mkdtemp(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("cache denied")

    monkeypatch.setattr(runner.tempfile, "mkdtemp", fail_mkdtemp)

    with pytest.raises(runner.SimulationError, match="cache staging directory"):
        runner.prepare_simulation_cache(fast=False)
