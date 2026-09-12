from __future__ import annotations

import pytest

from src.cpu.encoder.steps.encoder import encode_asm
from src.cpu.simulation.runner import run_snapshot


def test_multi_byte_space_literal_is_a_byte_sequence() -> None:
    result = run_snapshot(
        """
space:
    wide = 0110011000000000
main:
    MOVM R0, [wide]
    MOV R1, [wide]
""",
        mem_start=0,
        mem_end=8,
        max_cycles=50_000,
    )
    assert result["registers"]["R0"]["dec"] == 0x0066, "MOVM byte order changed"
    assert result["registers"]["R1"]["dec"] == 0x66, "first byte is not at the lowest address"


def test_single_byte_space_literal_is_unchanged() -> None:
    result = run_snapshot(
        """
space:
    narrow = 11110000
main:
    MOV R0, [narrow]
""",
        mem_start=0,
        mem_end=8,
        max_cycles=50_000,
    )
    assert result["registers"]["R0"]["dec"] == 0xF0


def test_operand2_above_12_bits_is_rejected() -> None:
    with pytest.raises(Exception, match="12-bit field"):
        run_snapshot("main:\n    MOV R7, V4096\n", mem_start=0, mem_end=4,
                     max_cycles=50_000)


def test_v_expression_obeys_operand2_width_and_points_to_wide_load() -> None:
    assert len(encode_asm(["MOV R0, V(1 << 11)"])) == 1

    with pytest.raises(ValueError, match="Operand2 does not fit") as exc_info:
        encode_asm(["MOV R0, V(1 << 15)"])

    message = str(exc_info.value)
    assert "12-bit field (0..4095)" in message
    assert "V(expr)" in message
    assert "MOV Rd, =expr" in message


def test_same_expression_can_use_wide_load_or_branch_target() -> None:
    expanded = encode_asm(["MOV R0, =1 << 15"])
    expected = encode_asm(["MOV R0, V128", "LSL R0, V8"])
    assert expanded == expected

    branch = encode_asm(["B V(1 << 15)"])[0]
    assert branch & 0xFFFFF == 1 << 15
    with pytest.raises(ValueError, match="20-bit field"):
        encode_asm(["B V(1 << 20)"])


def test_shift_amount_keeps_its_narrower_range() -> None:
    assert len(encode_asm(["LSL R0, V31"])) == 1
    with pytest.raises(ValueError, match=r"Shift amount out of range \(0\.\.31\)"):
        encode_asm(["LSL R0, V32"])


def test_largest_valid_immediate_still_assembles() -> None:
    result = run_snapshot("main:\n    MOV R0, V4095\n", mem_start=0, mem_end=4,
                          max_cycles=50_000)
    assert result["registers"]["R0"]["dec"] == 4095
