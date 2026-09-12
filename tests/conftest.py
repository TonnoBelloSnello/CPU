from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from src.cpu.simulation.rtl_config import RAM_ADDR_WIDTH
from src.cpu.simulation.runner import (
    _assemble_program as _assemble_program_impl,
)
from src.cpu.simulation.runner import run_program_trace
from src.cpu.simulation.snapshot import MemoryCell, Snapshot
from src.cpu.simulation.templates import render_loader_sv as _render_loader_sv_impl

ROOT = Path(__file__).resolve().parent.parent
MAX_ADDR_VALUE = (1 << RAM_ADDR_WIDTH) - 1


def _cell_map(cells: list[MemoryCell], mask: int | None = None) -> dict[int, int]:
    return {
        cell["addr"]: cell["dec"] if mask is None else cell["dec"] & mask
        for cell in cells
        if cell["dec"] is not None
    }


def register_value(snapshot: Snapshot, name: str) -> int:
    value = snapshot["registers"][name]["dec"]
    assert value is not None, f"{name} was reported as X/Z"
    return value


def memory_map(snapshot: Snapshot) -> dict[int, int]:
    return _cell_map(snapshot["memory"])


def framebuffer_map(snapshot: Snapshot) -> dict[int, int]:
    return _cell_map(snapshot["framebuffer"], 0xFF)


def _assemble_program(lines: list[str]) -> tuple[bytes, dict[str, int]]:
    return _assemble_program_impl(lines, require_encoded_instructions=False)


def _render_loader_sv(program_bytes: bytes) -> str:
    return _render_loader_sv_impl(
        program_bytes,
        addr_width=RAM_ADDR_WIDTH,
        generated_by="pytest",
        emit_loader_done=True,
    )


def run_simulation(
    program_lines: list[str], *, expect_halt: bool = True
) -> tuple[str, dict[str, int]]:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")

    return run_program_trace(program_lines, expect_halt=expect_halt)


def assert_result(output: str, value: int, *, dest: str | None = None, found: bool = True) -> None:
    pattern = rf"Storing result\s+{value}\b"
    if dest is not None:
        pattern += rf".*\b{dest}"
    where = f" in {dest}" if dest else ""
    if found:
        assert re.search(pattern, output) is not None, f"Missing result {value}{where} in output"
    else:
        assert re.search(pattern, output) is None, f"Unexpected result {value}{where} in output"


def assert_register(output: str, register: int, value: int, *, found: bool = True) -> None:
    assert_result(output, value, dest=rf"R{register}\b", found=found)
