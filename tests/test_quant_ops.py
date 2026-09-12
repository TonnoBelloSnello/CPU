from __future__ import annotations

import shutil

import pytest
from conftest import assert_register, run_simulation

from src.cpu.simulation.emulator import run_emulator_snapshot
from src.cpu.simulation.runner import _assemble_program, run_snapshot


def _u16(value: int) -> int:
    return value & 0xFFFF


def test_saturating_add_and_subtract_clamp_instead_of_wrapping() -> None:
    output, _ = run_simulation([
        "main:",
        "MOV R0, V200",
        "MOV R1, V100",
        "QADD R2, R0, R1",
        "MOV R3, =32700",
        "QADD R4, R3, R1",
        "MOV R5, =32768",
        "QSUB R6, R5, R1",
        "QSUB R7, R0, R1",
    ])

    assert_register(output, 2, 300)
    assert_register(output, 4, 32767)
    assert_register(output, 6, _u16(-32768))
    assert_register(output, 7, 100)


def test_negative_immediate_swaps_saturating_add_and_subtract() -> None:
    output, _ = run_simulation([
        "main:",
        "MOV R0, V200",
        "QADD R1, R0, V-50",
        "QSUB R2, R0, V-50",
    ])

    assert_register(output, 1, 150)
    assert_register(output, 2, 250)


def test_signed_and_unsigned_saturation_narrow_to_a_byte() -> None:
    output, _ = run_simulation([
        "main:",
        "MOV R0, V300",
        "SSAT R1, R0, V8",
        "USAT R2, R0, V8",
        "MOV R3, =65236",
        "SSAT R4, R3, V8",
        "USAT R5, R3, V8",
        "MOV R6, V100",
        "SSAT R7, R6, V8",
        "SSAT R8, R6, V0",
    ])

    assert_register(output, 1, 127)
    assert_register(output, 2, 255)
    assert_register(output, 4, _u16(-128))
    assert_register(output, 5, 0)
    assert_register(output, 7, 100)
    assert_register(output, 8, 100)


def test_rounding_doubling_high_multiply_matches_gemmlowp() -> None:
    output, _ = run_simulation([
        "main:",
        "MOV R0, =16384",
        "QRDMULH R1, R0, R0",
        "MOV R2, =32768",
        "QRDMULH R3, R2, R2",
        "MOV R4, =32767",
        "QRDMULH R5, R4, R0",
    ])

    assert_register(output, 1, 8192)
    assert_register(output, 3, 32767)
    assert_register(output, 5, 16384)


def test_rounding_shift_right_rounds_half_away_from_zero() -> None:
    output, _ = run_simulation([
        "main:",
        "MOV R0, V5",
        "RSHR R1, R0, V1",
        "MOV R2, V4",
        "RSHR R3, R2, V1",
        "MOV R4, =65531",
        "RSHR R5, R4, V1",
        "MOV R6, V7",
        "RSHR R7, R6, V0",
    ])

    assert_register(output, 1, 3)
    assert_register(output, 3, 2)
    assert_register(output, 5, _u16(-3))
    assert_register(output, 7, 7)


def test_relu_uses_a_zero_ceiling_to_mean_unbounded() -> None:
    output, _ = run_simulation([
        "main:",
        "SXTB R0, V200",
        "RELU R1, R0, V0",
        "MOV R2, V200",
        "RELU R3, R2, V0",
        "RELU R4, R2, V6",
        "MOV R5, V3",
        "RELU R6, R5, V6",
    ])

    assert_register(output, 1, 0)
    assert_register(output, 3, 200)
    assert_register(output, 4, 6)
    assert_register(output, 6, 3)


def test_sign_extend_byte_recovers_a_negative_weight_from_a_load() -> None:
    output, _ = run_simulation([
        "space:",
        "    weights = {{200, 100}}",
        "main:",
        "MOV R0, [weights]",
        "SXTB R1, R0",
        "MOV R2, =weights",
        "ADD R2, R2, V1",
        "MOV R3, [R2]",
        "SXTB R4, R3",
    ])

    assert_register(output, 1, _u16(-56))
    assert_register(output, 4, 100)


def test_requantization_pipeline_reproduces_a_tflite_output_scale() -> None:
    output, _ = run_simulation([
        "main:",
        "MOV R0, V1000",
        "MOV R1, =26214",
        "QRDMULH R2, R0, R1",
        "RSHR R3, R2, V4",
        "SSAT R4, R3, V8",
        "MOV R5, V4000",
        "QRDMULH R6, R5, R1",
        "RSHR R7, R6, V4",
        "SSAT R8, R7, V8",
    ])

    assert_register(output, 2, 800)
    assert_register(output, 3, 50)
    assert_register(output, 4, 50)
    assert_register(output, 6, 3200)
    assert_register(output, 7, 200)
    assert_register(output, 8, 127)


def test_quant_ops_are_conditional_like_every_other_instruction() -> None:
    output, _ = run_simulation([
        "main:",
        "MOV R0, V300",
        "CMP R0, V0",
        "SSATEQ R1, R0, V8",
        "SSATNE R2, R0, V8",
    ])

    assert_register(output, 1, 127, found=False)
    assert_register(output, 2, 127)


@pytest.mark.parametrize(
    "body",
    [
        """
            MOV R0, =32700
            QADD R1, R0, V100
            QSUB R2, R0, V-100
            MOV R3, =65236
            SSAT R4, R3, V8
            USAT R5, R3, V8
            MOV R6, =16384
            QRDMULH R7, R6, R6
            RSHR R8, R6, V3
            SXTB R9, V200
            RELU R10, R9, V0
        """,
        """
            MOV R0, =65531
            RSHR R1, R0, V1
            RSHR R2, R0, V2
            SSAT R3, R0, V4
            USAT R4, R0, V4
            MOV R5, V255
            SXTB R6, R5
            RELU R7, R5, V6
            QADD R8, R5, R5
            QSUB R9, R5, R5
        """,
    ],
)
def test_fast_emulator_matches_rtl_for_quant_ops(body: str) -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")
    source = "main:\n" + body

    image, labels = _assemble_program(source.splitlines())
    fast = run_emulator_snapshot(
        image, labels=labels, mem_start=0, mem_end=32, max_cycles=20_000
    )
    rtl = run_snapshot(source, mem_start=0, mem_end=32, max_cycles=20_000)

    assert fast["registers"] == rtl["registers"]
    assert fast["memory"] == rtl["memory"]
