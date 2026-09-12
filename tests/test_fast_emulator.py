from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from src.cpu.simulation.emulator import (
    CPUEmulator,
    EmulationTimeoutError,
    run_emulator_snapshot,
    stream_emulator_events,
)
from src.cpu.simulation.runner import _assemble_program, run_snapshot
from src.cpu.simulation.snapshot import Snapshot

ROOT = Path(__file__).resolve().parent.parent


def _assemble(source: str) -> tuple[bytes, dict[str, int]]:
    return _assemble_program(source.splitlines())


def _fast(source: str, *, mem_end: int = 96, key_mask: int = 0) -> Snapshot:
    image, labels = _assemble(source)
    return run_emulator_snapshot(
        image,
        labels=labels,
        mem_start=0,
        mem_end=mem_end,
        key_mask=key_mask,
        max_cycles=20_000,
    )


def _assert_architectural_parity(source: str, *, mem_end: int = 96, key_mask: int = 0) -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")
    fast = _fast(source, mem_end=mem_end, key_mask=key_mask)
    rtl = run_snapshot(
        source,
        mem_start=0,
        mem_end=mem_end,
        key_mask=key_mask,
        max_cycles=20_000,
    )
    assert fast["registers"] == rtl["registers"]
    assert fast["memory"] == rtl["memory"]
    assert fast["framebuffer"] == rtl["framebuffer"]


def test_fast_emulator_matches_rtl_for_alu_conditions_aliases_and_shifts() -> None:
    _assert_architectural_parity(
        """
        main:
            MOV R0, V4095
            MOV R1, V1
            ADD R2, R0, R1
            LSL R2, V3
            ROR R3, R2, V4
            CMP R3, V0
            ADCNE R4, R1, V2
            SBC R5, R4, V1
            MOV LE, R5
            ADD HEX, R5, V7
            MOV R6, HEX
            ABS R7, R3
            MAX R8, R7, R6
            MIN R9, R8, R8
            MADD R9, R1, V5
        """
    )


def test_fast_emulator_matches_rtl_for_harvard_memory_stack_and_control_flow() -> None:
    _assert_architectural_parity(
        """
        space:
            value = 0
        main:
            MOV R0, V511
            SAVEM R0, [value]
            MOVM R1, [value]
            PUSH R1
            BL helper
            POP R3
            B done
        helper:
            MOV R2, LR
            MOV PC, LR
        done:
            SAVE R3, [R2]
        """,
        mem_end=64,
    )


def test_fast_emulator_matches_rtl_for_fp_edges() -> None:
    _assert_architectural_parity(
        """
        space:
            nan_bits = 0111111000000000
            subnormal_bits = 0000000000000001
        main:
            MOVM R0, [nan_bits]
            MOVM R1, [subnormal_bits]
            FMOV R2, F1.5
            FADD R3, R2, F0.5
            FSUB R4, R2, F0.5
            FMUL R5, R2, F0.5
            FDIV R6, R2, F0.5
            FADD R7, R1, R2
            FCMP R0, R2
            MOVVS R8, V99
        """
    )


@pytest.mark.parametrize(
    ("numerator_bits", "denominator_bits", "expected_bits"),
    [
        (0x152F, 0x4F1A, 0x06EB),
        (0x11B6, 0x4B21, 0x0734),
        (0xB285, 0x6B2D, 0x87A2),
    ],
)
def test_fast_emulator_matches_rtl_fdiv_underflow_normalization(
    numerator_bits: int, denominator_bits: int, expected_bits: int
) -> None:
    numerator_literal = ((numerator_bits & 0xFF) << 8) | (numerator_bits >> 8)
    denominator_literal = ((denominator_bits & 0xFF) << 8) | (denominator_bits >> 8)
    source = f"""space:
        numerator = {numerator_literal:016b}
        denominator = {denominator_literal:016b}
    main:
        MOVM R0,[numerator]
        MOVM R1,[denominator]
        FDIV R2,R0,R1
    """
    fast = _fast(source)
    assert fast["registers"]["R2"]["dec"] == expected_bits
    _assert_architectural_parity(source)


def test_fast_emulator_matches_rtl_for_matrix_text_pixels_and_keys() -> None:
    _assert_architectural_parity(
        """
        space:
            a = {{1, 2, 3}, {4, 5, 6}}
            b = {{7, 8}, {9, 10}, {11, 12}}
        main:
            MUL R0, a, b
            MOV R1, V1
            MOV R2, V2
            PIXELNB R1, R2, V31
            TEXT V4, V5, "A?", V224
            WAITKNB R3, V5
            WAITK R4, V4
        """,
        mem_end=96,
        key_mask=0b0100,
    )


def test_waitk_without_selected_key_exhausts_budget_without_host_sleep() -> None:
    image, labels = _assemble("main:\n WAITK R0, V1")
    with pytest.raises(EmulationTimeoutError, match="max_cycles=25"):
        run_emulator_snapshot(image, labels=labels, max_cycles=25)


def test_stream_emulator_deduplicates_pixel_events_and_returns_snapshot() -> None:
    image, labels = _assemble(
        """
        main:
            MOV R0, V1
            MOV R1, V2
            PIXEL R0, R1, V255
            PIXELNB R0, R1, V255
        """
    )
    events = list(
        stream_emulator_events(
            image,
            labels=labels,
            mem_start=0,
            mem_end=8,
            max_cycles=100,
        )
    )
    assert [event["type"] for event in events].count("pixel") == 1
    assert events[0]["type"] == "start"
    assert events[-2]["type"] == "snapshot"
    assert events[-1] == {"type": "done"}


@pytest.mark.skipif(
    os.environ.get("CPU_RUN_SLOW_EMULATOR_TESTS") != "1",
    reason="set CPU_RUN_SLOW_EMULATOR_TESTS=1 for the full 19,200-pixel RTL differential",
)
def test_raycaster_first_frame_matches_rtl() -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")
    source = (ROOT / "programs" / "raycaster.de1").read_text(encoding="utf-8")
    image, _labels = _assemble(source)
    emulator = CPUEmulator(image)
    fast_pixels: dict[int, int] = {}
    while len(fast_pixels) < 160 * 120:
        for event in emulator.step():
            fast_pixels[event["addr"]] = event["color"]

    rtl_pixels: dict[int, int] = {}
    stream = None
    try:
        from src.cpu.simulation.runner import stream_snapshot_events

        stream = stream_snapshot_events(source, mem_start=0, mem_end=0, max_cycles=2_000_000)
        for event in stream:
            if event["type"] == "pixel":
                rtl_pixels[event["addr"]] = event["color"]
                if len(rtl_pixels) == 160 * 120:
                    break
    finally:
        if stream is not None:
            stream.close()
    assert fast_pixels == rtl_pixels


def test_fast_emulator_matches_rtl_for_wide_branches_stack_slots_and_mmio() -> None:
    _assert_architectural_parity(
        """
        const MMIO = 0xFF00
        const KEYS = MMIO + 8
        space:
            slot = 0000000000000000
        main:
            MOV R4, V1000
            MOV R5, V2000
            MOV R6, V3000
            PUSH {R4-R6, LR}
            MOV R4, V0
            MOV R5, V0
            MOV R6, V0
            POP {R4-R6, LR}
            BL helper
            MOV R0, =MMIO
            MOV R1, V682
            SAVEM R1, [R0]
            MOV R2, LE
            MOV R3, =KEYS
            MOVM R7, [R3]
            SAVEM R4, [slot]
            B done
            MOV R8, V99
        helper:
            ADD R9, R5, R6
            MOV PC, LR
        done:
            ADD R10, R4, V0
        """
    )
