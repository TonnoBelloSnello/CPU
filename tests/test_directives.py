from pathlib import Path

import pytest
from conftest import assert_result, run_simulation

from src.cpu.encoder.steps.constload import expand_constant_load
from src.cpu.encoder.steps.directives import (
    MAX_INCLUDE_DEPTH,
    DirectiveError,
    evaluate_expression,
    expand_includes,
    expand_source,
    extract_constants,
)


def test_constant_expression_supports_bases_and_operators() -> None:
    constants = {"BASE": 0x8000}
    assert evaluate_expression("0x10", {}) == 16
    assert evaluate_expression("0b1010", {}) == 10
    assert evaluate_expression("1 << 15", {}) == 32768
    assert evaluate_expression("BASE + 4 * 32", constants) == 0x8000 + 128
    assert evaluate_expression("(BASE >> 8) & 0xFF", constants) == 0x80


def test_constant_expression_rejects_arbitrary_python() -> None:
    with pytest.raises(DirectiveError, match="Unsupported syntax"):
        evaluate_expression("__import__('os').getcwd()", {})
    with pytest.raises(DirectiveError, match="Undefined constant"):
        evaluate_expression("MISSING + 1", {})
    with pytest.raises(DirectiveError, match="Division by zero"):
        evaluate_expression("1 / 0", {})


def test_constants_may_build_on_earlier_constants() -> None:
    remaining, constants = extract_constants(
        [
            "const TEX_BASE = 0x8000",
            "const MAP_BASE = TEX_BASE + 0x1000",
            "main:",
            "    MOV R0, V1",
        ]
    )

    assert constants == {"TEX_BASE": 0x8000, "MAP_BASE": 0x9000}
    assert [line.strip() for line in remaining] == ["main:", "MOV R0, V1"]


def test_duplicate_constant_is_rejected() -> None:
    with pytest.raises(DirectiveError, match="Duplicate constant"):
        extract_constants(["const A = 1", "const A = 2"])


def test_include_splices_a_file_and_detects_cycles(tmp_path: Path) -> None:
    (tmp_path / "shared.de1").write_text("const SHARED = 7\n", encoding="utf-8")
    lines = expand_includes(['include "shared.de1"', "main:"], tmp_path)
    assert [line.strip() for line in lines] == ["const SHARED = 7", "main:"]

    (tmp_path / "loop.de1").write_text('include "loop.de1"\n', encoding="utf-8")
    with pytest.raises(DirectiveError, match="Circular include"):
        expand_includes(['include "loop.de1"'], tmp_path)


def test_include_without_a_source_directory_is_reported() -> None:
    with pytest.raises(DirectiveError, match="only available when assembling a file"):
        expand_includes(['include "x.de1"'], None)


def test_include_depth_limit_and_nested_relative_paths(tmp_path: Path) -> None:
    for index in range(MAX_INCLUDE_DEPTH + 1):
        (tmp_path / f"{index}.de1").write_text(
            f'include "{index + 1}.de1"\n', encoding="utf-8"
        )
    with pytest.raises(DirectiveError, match="nested deeper"):
        expand_includes(['include "0.de1"'], tmp_path)


def test_include_locations_survive_expansion(tmp_path: Path) -> None:
    child = tmp_path / "child.de1"
    child.write_text("# comment\nspace:\n data: 2", encoding="utf-8")
    result = expand_source(['include "child.de1"', "main:", " MOV R0, V0"], tmp_path)
    assert [(line.path, line.line) for line in result.lines] == [
        (child, 0), (child, 1), (child, 2), (None, 1), (None, 2),
    ]


@pytest.mark.parametrize("source", ["include", "include missing.de1", 'include "bad.de1"'])
def test_invalid_include_is_a_directive_error(tmp_path: Path, source: str) -> None:
    with pytest.raises(DirectiveError):
        expand_includes([source], tmp_path)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, ["MOV R0, V0"]),
        (4095, ["MOV R0, V4095"]),
        (0x6600, ["MOV R0, V102", "LSL R0, V8"]),
        (0x9400, ["MOV R0, V148", "LSL R0, V8"]),
        (0x1234, ["MOV R0, V18", "LSL R0, V8", "ORR R0, R0, V52"]),
    ],
)
def test_constant_load_expansion_is_minimal(value: int, expected: list[str]) -> None:
    assert expand_constant_load("R0", value, 0xE) == expected


def test_constant_load_keeps_the_condition_on_every_word() -> None:
    assert expand_constant_load("R1", 0x1234, 0x0) == [
        "MOVEQ R1, V18",
        "LSLEQ R1, V8",
        "ORREQ R1, R1, V52",
    ]


def test_constants_and_wide_load_build_a_high_address() -> None:
    program = [
        "const TEX_BASE = 0x8000",
        "const MAP_BASE = TEX_BASE + 0x1000",
        "main:",
        "MOV R0, =MAP_BASE",
        "MOV R1, V42",
        "SAVE R1, [R0]",
        "MOV R2, [R0]",
        "ADD R3, R2, V0",
        "MOV R4, =TEX_BASE",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 42, dest=r"R3\b")
    assert_result(output, 0x9000, dest=r"R0\b")
    assert_result(output, 0x8000, dest=r"R4\b")


def test_constant_resolves_as_a_plain_immediate_operand() -> None:
    program = [
        "const STRIDE = 32",
        "main:",
        "MOV R0, V4",
        "MUL R1, R0, STRIDE",
        "ADD R2, R1, V(STRIDE / 2)",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 128, dest=r"R1\b")
    assert_result(output, 144, dest=r"R2\b")


def test_reserved_size_accepts_a_constant_expression() -> None:
    program = [
        "const ROWS = 4",
        "const COLS = 8",
        "space:",
        "    grid: ROWS * COLS",
        "    tail = 00000101",
        "main:",
        "MOV R0, tail",
    ]

    output, labels = run_simulation(program)

    assert labels["grid"] == 4
    assert labels["tail"] == 4 + 32
    assert_result(output, 36, dest=r"R0\b")


def test_labels_after_a_wide_load_still_resolve() -> None:
    program = [
        "main:",
        "MOV R0, =0x1234",
        "B target",
        "MOV R1, V99",
        "target:",
        "ADD R2, R0, V0",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 0x1234, dest=r"R2\b")
    assert_result(output, 99, found=False)


def test_wide_load_referencing_a_code_label_is_rejected() -> None:
    program = [
        "main:",
        "MOV R0, =target",
        "target:",
        "MOV R1, V1",
    ]

    from src.cpu.simulation.runner import SimulationError

    with pytest.raises(SimulationError, match="not code labels"):
        run_simulation(program)
