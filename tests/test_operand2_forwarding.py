from __future__ import annotations

import struct

import pytest
from conftest import register_value

from src.cpu.simulation.runner import run_snapshot
from src.cpu.simulation.snapshot import Snapshot


def _run(program: str) -> Snapshot:
    return run_snapshot(program, mem_start=0, mem_end=4, max_cycles=50_000)


def _as_signed(value: int) -> int:
    return value - 65536 if value >= 32768 else value


def _as_fp16(bits: int) -> float:
    return struct.unpack("<e", struct.pack("<H", bits & 0xFFFF))[0]


def test_fp_result_is_forwarded_to_operand2() -> None:
    result = _run("""
main:
    MOV R7, V0
    FMOV R6, F3.0
    FMUL R6, R6, F4.0
    FADD R7, R7, R6
""")
    assert _as_fp16(register_value(result, "R6")) == 12.0
    assert _as_fp16(register_value(result, "R7")) == 12.0


def test_fp_result_is_forwarded_to_an_integer_consumer() -> None:
    result = _run("""
main:
    MOV R7, V0
    FMOV R6, F3.0
    FMUL R6, R6, F4.0
    ADD R7, R7, R6
""")
    assert register_value(result, "R7") == 0x4A00


def test_branch_class_result_is_forwarded_to_operand2() -> None:
    result = _run("""
main:
    MOV R1, V0
    SUB R1, R1, V5
    ABS R1, R1
    MUL R1, R1, R1
""")
    assert _as_signed(register_value(result, "R1")) == 25


def test_shift_result_is_forwarded_to_operand2() -> None:
    result = _run("""
main:
    MOV R1, V1
    LSL R1, V15
    MOV R2, R1
""")
    assert register_value(result, "R2") == 0x8000


def test_shifted_register_operand2_is_forwarded() -> None:
    result = _run("""
main:
    MOV R0, V3
    AND R1, R0, V255
    MOV R2, V10
    ADD R2, R2, R1 LSL V1
""")
    assert register_value(result, "R2") == 16


@pytest.mark.parametrize("fillers", [0, 1, 2])
def test_forwarding_does_not_depend_on_instruction_spacing(fillers: int) -> None:
    padding = "\n".join(["    MOV R9, V0"] * fillers)
    result = _run(f"""
main:
    FMOV R0, F3.0
    FMOV R2, F10.0
    FADD R0, R0, F1.0
{padding}
    FMUL R1, R2, R0
""")
    assert _as_fp16(register_value(result, "R1")) == 40.0
