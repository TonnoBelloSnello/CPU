from __future__ import annotations

import re

from conftest import assert_result, run_simulation

from src.cpu.simulation.runner import run_snapshot

PIXEL_RE = re.compile(r"PIXEL:\s*x=(\d+)\s+y=(\d+)\s+color=(\d+)\s+addr=(\d+)")


def _pixels(output: str) -> list[tuple[int, ...]]:
    return [tuple(int(v) for v in m.groups()) for m in PIXEL_RE.finditer(output)]


def test_text_immediate_coordinates_and_literal_source() -> None:
    program = [
        "main:",
        'TEXT V1, V2, "A"',
    ]

    output, _ = run_simulation(program)
    pixels = _pixels(output)

    assert pixels
    assert all(x >= 1 and y >= 2 for x, y, _, _ in pixels)
    assert all(0 <= x < 160 and 0 <= y < 120 for x, y, _, _ in pixels)
    assert all(color == 255 for _, _, color, _ in pixels)


def test_text_register_coordinates() -> None:
    program = [
        "main:",
        "MOV R0, V10",
        "MOV R1, V5",
        'TEXT R0, R1, "B"',
    ]

    output, _ = run_simulation(program)
    pixels = _pixels(output)

    assert pixels
    assert all(x >= 10 and y >= 5 for x, y, _, _ in pixels)


def test_text_optional_color_operand() -> None:
    program = [
        "main:",
        'TEXT V0, V0, "C", V77',
    ]

    output, _ = run_simulation(program)
    pixels = _pixels(output)

    assert pixels
    assert all(color == 77 for _, _, color, _ in pixels)


def test_text_string_label_source() -> None:
    program = [
        "space:",
        '    greeting = "Hi"',
        "main:",
        "TEXT V0, V0, greeting",
    ]

    output, _ = run_simulation(program)
    pixels = _pixels(output)

    assert pixels
    assert all(0 <= x < 160 and 0 <= y < 120 for x, y, _, _ in pixels)


def test_text_clips_at_framebuffer_edges() -> None:
    program = [
        "main:",
        'TEXT V157, V115, "W"',
    ]

    output, _ = run_simulation(program)
    pixels = _pixels(output)

    assert pixels
    assert all(0 <= x < 160 and 0 <= y < 120 for x, y, _, _ in pixels)


def test_text_max_character_cap_is_16() -> None:
    short_program = [
        "main:",
        'TEXT V0, V0, "ABCDEFGHIJKLMNOP"',
    ]
    long_program = [
        "main:",
        'TEXT V0, V0, "ABCDEFGHIJKLMNOPZZZZ"',
    ]

    short_output, _ = run_simulation(short_program)
    long_output, _ = run_simulation(long_program)

    assert _pixels(short_output) == _pixels(long_output)


def test_text_condition_code_behavior() -> None:
    met_program = [
        "main:",
        "MOV R0, V1",
        "CMP R0, V1",
        'TEXTEQ V0, V0, "A"',
    ]
    not_met_program = [
        "main:",
        "MOV R0, V1",
        "CMP R0, V2",
        'TEXTEQ V0, V0, "A"',
    ]

    met_output, _ = run_simulation(met_program)
    not_met_output, _ = run_simulation(not_met_program)

    assert _pixels(met_output)
    assert not _pixels(not_met_output)


def test_text_preserves_full_width_temporary_registers() -> None:
    program = [
        "main:",
        "MOV R8, V291",
        "MOV R9, V1110",
        "MOV R12, V2748",
        'TEXT V0, V0, "A", V77',
        "MOV R0, R8",
        "MOV R1, R9",
        "MOV R2, R12",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 291, dest=r"R0\b")
    assert_result(output, 1110, dest=r"R1\b")
    assert_result(output, 2748, dest=r"R2\b")


def test_text_reads_aliased_coordinate_and_color_sources_before_clobbering() -> None:
    program = [
        "main:",
        "MOV R8, V11",
        "MOV R9, V7",
        "MOV R12, V66",
        'TEXT R12, R8, "A", R9',
    ]

    output, _ = run_simulation(program)
    pixels = _pixels(output)

    assert pixels
    assert all(x >= 66 and y >= 11 for x, y, _, _ in pixels)
    assert all(color == 7 for _, _, color, _ in pixels)


def test_label_addresses_after_text_expansion_remain_correct() -> None:
    program = [
        "main:",
        "MOV R0, V1",
        'TEXT V0, V0, "A"',
        "B after_text",
        "MOV R1, V99",
        "after_text:",
        "MOV R2, V7",
    ]

    output, _ = run_simulation(program)

    assert "Storing result 99" not in output
    assert_result(output, 7)


def test_stream_runner_label_resolution_with_text_expansion() -> None:
    program = "\n".join(
        [
            "main:",
            "MOV R0, V1",
            'TEXT V0, V0, "A"',
            "B after_text",
            "MOV R1, V99",
            "after_text:",
            "MOV R2, V7",
        ]
    )

    snapshot = run_snapshot(program_text=program, mem_start=0, mem_end=8)
    log = str(snapshot["log"])

    assert "Storing result 99" not in log
    assert re.search(r"Storing result\s+7\b", log) is not None
