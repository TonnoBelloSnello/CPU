from __future__ import annotations

import shutil

import pytest
from conftest import assert_register, run_simulation

from src.cpu.simulation.emulator import run_emulator_snapshot
from src.cpu.simulation.runner import _assemble_program, run_snapshot


def _u16(value: int) -> int:
    return value & 0xFFFF


def test_vector_load_packs_lane_zero_from_the_lowest_address() -> None:
    output, _ = run_simulation([
        "space:",
        "    data = {{1, 2, 3, 253, 5, 6, 7, 8}}",
        "main:",
        "MOV R0, =data",
        "VLD Q0, [R0]",
        "VEXT R1, Q0, V0",
        "VEXT R2, Q0, V3",
        "VEXT R3, Q0, V7",
    ])

    assert_register(output, 1, 1)
    assert_register(output, 2, _u16(-3))
    assert_register(output, 3, 8)


def test_vector_store_round_trips_through_memory() -> None:
    output, _ = run_simulation([
        "space:",
        "    src = {{10, 20, 30, 40, 50, 60, 70, 80}}",
        "    dst: 8",
        "main:",
        "MOV R0, =src",
        "VLD Q1, [R0]",
        "MOV R1, =dst",
        "VST Q1, [R1]",
        "VLD Q2, [R1]",
        "VEXT R2, Q2, V0",
        "VEXT R3, Q2, V7",
        "MOV R4, [dst]",
    ])

    assert_register(output, 2, 10)
    assert_register(output, 3, 80)
    assert "MEM_LOAD: Loaded value 10" in output


def test_dot_product_accumulates_signed_lanes_across_calls() -> None:
    output, _ = run_simulation([
        "space:",
        "    a = {{1, 2, 3, 252, 0, 0, 0, 0}}",
        "    b = {{2, 2, 2, 2, 0, 0, 0, 0}}",
        "main:",
        "MOV R0, =a",
        "VLD Q0, [R0]",
        "MOV R1, =b",
        "VLD Q1, [R1]",
        "ACLR A0",
        "VDOT A0, Q0, Q1",
        "AGET R2, A0",
        "VDOT A0, Q0, Q1",
        "AGET R3, A0",
        "VSUM A1, Q0",
        "AGET R4, A1",
        "VMAXR R5, Q0",
    ])

    assert_register(output, 2, 4)
    assert_register(output, 3, 8)
    assert_register(output, 4, 2)
    assert_register(output, 5, 3)


def test_broadcast_insert_and_extract_address_individual_lanes() -> None:
    output, _ = run_simulation([
        "main:",
        "VDUP Q0, V7",
        "VEXT R0, Q0, V5",
        "MOV R1, V200",
        "VINS Q0, R1, V2",
        "VEXT R2, Q0, V2",
        "VEXT R3, Q0, V3",
        "VSUM A0, Q0",
        "AGET R4, A0",
    ])

    assert_register(output, 0, 7)
    assert_register(output, 2, _u16(-56))
    assert_register(output, 3, 7)
    assert_register(output, 4, _u16(-7))


def test_accumulator_seed_read_and_saturating_read() -> None:
    output, _ = run_simulation([
        "main:",
        "ASET A0, V1000",
        "AGET R0, A0",
        "MOV R1, =65036",
        "ASET A1, R1",
        "AGET R2, A1",
        "ACLR A2",
        "AGET R3, A2",
        "ASET A3, V1000",
        "MOV R4, =32767",
        "AQMUL A3, R4",
        "AGETS R5, A3",
    ])

    assert_register(output, 0, 1000)
    assert_register(output, 2, _u16(-500))
    assert_register(output, 3, 0)
    assert_register(output, 5, 1000)


def test_accumulator_requantization_matches_the_scalar_pipeline() -> None:
    output, _ = run_simulation([
        "main:",
        "ASET A0, V1000",
        "MOV R0, =26214",
        "AQMUL A0, R0",
        "AGET R1, A0",
        "ARSHR A0, V4",
        "AGET R2, A0",
        "MOV R3, =65531",
        "ASET A1, R3",
        "ARSHR A1, V1",
        "AGET R4, A1",
    ])

    assert_register(output, 1, 800)
    assert_register(output, 2, 50)
    assert_register(output, 4, _u16(-3))


def test_accumulator_holds_more_than_a_register_and_agets_saturates() -> None:
    output, _ = run_simulation([
        "space:",
        "    big = {{127, 127, 127, 127, 127, 127, 127, 127}}",
        "main:",
        "MOV R0, =big",
        "VLD Q0, [R0]",
        "ACLR A0",
        "VDOT A0, Q0, Q0",
        "VDOT A0, Q0, Q0",
        "AGETS R1, A0",
        "ARSHR A0, V4",
        "AGETS R2, A0",
    ])

    assert_register(output, 1, 32767)
    assert_register(output, 2, 16129)


def test_vector_ops_are_conditional() -> None:
    output, _ = run_simulation([
        "main:",
        "VDUP Q0, V5",
        "CMP R0, V0",
        "VSUMNE A0, Q0",
        "VSUMEQ A0, Q0",
        "AGET R1, A0",
    ])

    assert_register(output, 1, 40)


def test_eight_lane_dot_product_beats_the_scalar_loop_it_replaces() -> None:
    output, _ = run_simulation([
        "space:",
        "    xs = {{3, 1, 4, 1, 5, 9, 2, 6}}",
        "    ws = {{1, 255, 1, 255, 1, 255, 1, 255}}",
        "main:",
        "MOV R0, =xs",
        "VLD Q0, [R0]",
        "MOV R1, =ws",
        "VLD Q1, [R1]",
        "ACLR A0",
        "VDOT A0, Q0, Q1",
        "AGET R2, A0",
        "MOV R3, V0",
        "MOV R4, =xs",
        "MOV R5, =ws",
        "MOV R6, V0",
        "loop:",
        "MOV R7, [R4]",
        "SXTB R7, R7",
        "MOV R8, [R5]",
        "SXTB R8, R8",
        "MADD R3, R7, R8",
        "ADD R4, R4, V1",
        "ADD R5, R5, V1",
        "ADD R6, R6, V1",
        "CMP R6, V8",
        "BNE loop",
    ])

    assert_register(output, 2, _u16(-3))
    assert_register(output, 3, _u16(-3))


@pytest.mark.parametrize(
    "body",
    [
        """
        space:
            src = {{1, 2, 3, 252, 5, 250, 7, 8}}
            dst: 8
        main:
            MOV R0, =src
            VLD Q0, [R0]
            VDUP Q1, V3
            ACLR A0
            VDOT A0, Q0, Q1
            VSUM A1, Q0
            VMAXR R1, Q0
            VEXT R2, Q0, V5
            MOV R3, V9
            VINS Q1, R3, V0
            MOV R4, =dst
            VST Q1, [R4]
            AGET R5, A0
            AGETS R6, A1
        """,
        """
        space:
            big = {{127, 127, 127, 127, 127, 127, 127, 127}}
        main:
            MOV R0, =big
            VLD Q2, [R0]
            ACLR A2
            VDOT A2, Q2, Q2
            VDOT A2, Q2, Q2
            AGETS R1, A2
            MOV R2, =26214
            AQMUL A2, R2
            ARSHR A2, V3
            AGET R3, A2
            MOV R5, =65436
            ASET A3, R5
            ARSHR A3, V2
            AGET R4, A3
        """,
    ],
)
def test_fast_emulator_matches_rtl_for_vector_state(body: str) -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")

    image, labels = _assemble_program(body.splitlines())
    fast = run_emulator_snapshot(
        image, labels=labels, mem_start=0, mem_end=48, max_cycles=20_000
    )
    rtl = run_snapshot(body, mem_start=0, mem_end=48, max_cycles=20_000)

    assert fast["registers"] == rtl["registers"]
    assert fast["memory"] == rtl["memory"]
