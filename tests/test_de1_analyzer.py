from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from src.cpu.encoder import analyze as analyzer
from src.cpu.encoder.analyze import AnalysisResult, analyze_text
from src.cpu.encoder.assemble import assemble, layout_source


def _messages(result: AnalysisResult) -> list[str]:
    return [item["message"] for item in result["diagnostics"]]


def test_analyzer_reports_sections_variables_and_labels_for_valid_program() -> None:
    program = "\n".join(
        [
            "space:",
            '    title = "CPU"',
            "    buffer: 16",
            "main:",
            "loop:",
            "    TEXT V0, V1, title",
            "    B loop",
        ]
    )

    result = analyze_text(program)

    assert result["diagnostics"] == []
    definitions = {
        (item["name"], item["kind"])
        for item in result["definitions"]
    }
    assert ("space", "section") in definitions
    assert ("title", "variable") in definitions
    assert ("buffer", "variable") in definitions
    assert ("main", "section") in definitions
    assert ("loop", "label") in definitions


@pytest.mark.parametrize(
    ("lines", "expected_message"),
    [
        (("main:", "    NOPE R0, V1"), "Invalid operation"),
        (("main:", "    ADD R0"), "expects 3 operand"),
        (("main:", "    B missing_label"), "Undefined label or variable"),
        (("space:", "    bad = 10201", "main:"), "invalid binary value"),
        (
            ("space:", "    counter = 1", "main:", "    TEXT V0, V0, counter"),
            "is defined but is not a string variable",
        ),
        (
            ("space:", "    A = {{1, 2}, {3}}", "main:"),
            "Matrix rows must be non-empty and equal length",
        ),
        (("main:", "    FMOV R0, F1_5"), "Invalid FP literal"),
    ],
    ids=[
        "invalid-opcode",
        "invalid-operand-count",
        "undefined-label",
        "invalid-space-binary",
        "invalid-text-source",
        "ragged-matrix",
        "invalid-fp-literal",
    ],
)
def test_analyzer_reports_diagnostic(lines: tuple[str, ...], expected_message: str) -> None:
    result = analyze_text("\n".join(lines))

    assert any(expected_message in message for message in _messages(result))


def test_analyzer_accepts_le_hex_and_waitknb_forms() -> None:
    result = analyze_text(
        "\n".join(
            [
                "main:",
                "    MOV LE, V1",
                "    MOV HEX, LE",
                "    WAITKNB R2, V15",
                "    ADD R0, R1, HEX",
            ]
        )
    )

    assert result["diagnostics"] == []


def test_analyzer_sizes_reservations_with_constant_expressions_like_the_assembler() -> None:
    valid = analyze_text(
        "\n".join(
            [
                "const CELL = 4",
                "const GRID = CELL * 8",
                "space:",
                "    grid: GRID",
                "    pad: 2 + 2",
                "main:",
                "    MOV R0, grid",
            ]
        )
    )
    assert valid["diagnostics"] == []

    invalid = analyze_text("space:\n    grid: UNKNOWN\nmain:\n    MOV R0, V1\n")
    assert any("Invalid size 'UNKNOWN'" in message for message in _messages(invalid))

    negative = analyze_text("space:\n    grid: -1\nmain:\n    MOV R0, V1\n")
    assert any("non-negative" in message for message in _messages(negative))


def test_analyzer_explains_v_expression_width_and_accepts_wide_contexts() -> None:
    invalid = analyze_text("main:\n    MOV R0, V(1 << 15)\n")
    messages = _messages(invalid)
    assert any("12-bit field (0..4095)" in message for message in messages)
    assert any("MOV Rd, =expr" in message for message in messages)

    valid = analyze_text(
        "\n".join(
            [
                "main:",
                "    MOV R0, =1 << 15",
                "    B V(1 << 15)",
                "    LSL R1, V31",
            ]
        )
    )
    assert valid["diagnostics"] == []

    branch_overflow = analyze_text("main:\n    B V(1 << 20)\n")
    assert any("20-bit field" in message for message in _messages(branch_overflow))

    shift_overflow = analyze_text("main:\n    LSL R1, V32\n")
    assert any("Shift amount out of range (0..31)" in message for message in _messages(shift_overflow))


def test_analyzer_keeps_main_as_a_branchable_code_label() -> None:
    result = analyze_text(
        "\n".join(
            [
                "main:",
                "    B main",
            ]
        )
    )

    assert result["diagnostics"] == []


def test_analyzer_keeps_helper_code_before_main() -> None:
    result = analyze_text(
        "\n".join(
            [
                "helper:",
                "    MOV R0, V1",
                "    MOV PC, LR",
                "main:",
                "    BL helper",
            ]
        )
    )

    assert result["diagnostics"] == []
    definitions = {(item["name"], item["kind"]) for item in result["definitions"]}
    assert ("helper", "label") in definitions
    assert ("main", "section") in definitions


def test_analyzer_layout_always_reserves_bootstrap_for_zero_byte_data() -> None:
    source = "\n".join(
        [
            "space:",
            "    empty: 0",
            "main:",
            "    MOV R0, empty",
        ]
    )
    layout = layout_source(source.splitlines(), {})
    program = assemble(source.splitlines())

    assert layout.symbols == program.symbols == {"empty": 4, "main": 4}
    assert layout.entry_address == program.entry_address == 4
    assert analyze_text(source)["diagnostics"] == []


def test_analyzer_accepts_entry_past_the_old_12_bit_bootstrap_limit() -> None:
    result = analyze_text(
        "\n".join(
            [
                "space:",
                "    buffer: 4092",
                "main:",
                "    MOV R0, V1",
            ]
        )
    )

    assert not any(
        diagnostic["code"] == "entry-address" for diagnostic in result["diagnostics"]
    )


def test_analyzer_reports_bootstrap_entry_overflow_using_real_reserved_size() -> None:
    result = analyze_text(
        "\n".join(
            [
                "space:",
                "    buffer: 1048572",
                "main:",
                "    MOV R0, V1",
            ]
        )
    )

    assert any(
        diagnostic["code"] == "entry-address"
        and "20-bit branch field" in str(diagnostic["message"])
        and diagnostic["line"] == 2
        for diagnostic in result["diagnostics"]
    )


def test_analyzer_counts_helper_words_when_checking_main_entry_range() -> None:
    result = analyze_text(
        "\n".join(
            [
                "space:",
                "    buffer: 1048568",
                "helper:",
                "    MOV R0, V1",
                "main:",
                "    B helper",
            ]
        )
    )

    assert any(
        diagnostic["code"] == "entry-address"
        and diagnostic["line"] == 4
        and "1048575" in str(diagnostic["message"])
        for diagnostic in result["diagnostics"]
    )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("main:\n    MOV R0, V0\nmain:\n    MOV R1, V1", "Duplicate code label"),
        ("main:\n    MOV R0, V0\nMAIN:\n    MOV R1, V1", "Duplicate code label 'main'"),
        ("bad-name:\n    MOV R0, V0", "Invalid code label"),
        ("__fp16_3C00:\n    MOV R0, V0", "reserved internal namespace"),
        ("R0:\n    MOV R1, V0", "reserved operand token"),
        ("space:\n    V5 = 00000000\nmain:\n    MOV R0, V0", "reserved operand token"),
        (
            "space:\n    item: 1\nitem:\n    MOV R0, V0",
            "defined as both data and a code label",
        ),
        ("space:\n    first: 1\nspace:\nmain:\n    MOV R0, V0", "Duplicate space"),
        ("main:\n    MOV R0, V0\nspace:\n    late: 1", "must precede executable code"),
        ("main:", "contains no instructions"),
    ],
)
def test_analyzer_matches_cli_source_structure_validation(source: str, message: str) -> None:
    result = analyze_text(source)

    assert any(message in str(item["message"]) for item in result["diagnostics"])


@pytest.mark.parametrize("instruction", ["LSL R0, #2", "LSL R0, R1, #2"])
def test_analyzer_accepts_hash_prefixed_shift_amounts(instruction: str) -> None:
    result = analyze_text(f"main:\n    {instruction}\n")

    assert result["diagnostics"] == []


@pytest.mark.parametrize(
    "instruction",
    [
        "ADD R0, R1, {",
        'MOV R0, "unterminated',
        'TEXT V0, V0, "unterminated',
        "MOV R0, [missing",
    ],
)
def test_analyzer_returns_diagnostics_for_incomplete_editor_input(instruction: str) -> None:
    result = analyze_text(f"main:\n    {instruction}\n")

    assert result["diagnostics"]


def test_analyzer_accepts_the_quantized_inference_extension() -> None:
    program = "\n".join(
        [
            "space:",
            "    buf: 16",
            "main:",
            "    MOV R0, =buf",
            "    VLD Q0, [R0]",
            "    VDUP Q1, V3",
            "    ACLR A0",
            "    VDOT A0, Q0, Q1",
            "    ARSHR A0, V4",
            "    AGETS R1, A0",
            "    SSAT R1, R1, V8",
            "    RELU R2, R1, V6",
            "    NPUCFG MODE, V(NPU_MAXPOOL)",
            "    NPUCFG IN_BASE, R0",
            "    NPURUN R3",
        ]
    )

    assert analyze_text(program)["diagnostics"] == []


def test_analyzer_rejects_malformed_vector_and_tensor_operands() -> None:
    cases = {
        "    VDOT R0, Q0, Q1": "accumulator",
        "    VDOT A0, R1, Q1": "vector register",
        "    VLD Q0, R1": "memory operand",
        "    NPUCFG NOT_A_FIELD, V0": "Unknown NPU configuration field",
        "    VEXT R0, Q0, V9": "Lane index out of range",
        "    ACLR A9": "Accumulator out of range",
        "    VLD Q8, [R0]": "Vector register out of range",
    }
    for line, expected in cases.items():
        program = "\n".join(["main:", line])
        messages = _messages(analyze_text(program))
        assert any(expected in message for message in messages), (line, messages)


def test_analyzer_rejects_shadowing_a_builtin_npu_constant() -> None:
    program = "\n".join(["const NPU_CONV = 9", "main:", "    MOV R0, V1"])

    messages = _messages(analyze_text(program))
    assert any("NPU_CONV" in message for message in messages), messages


@pytest.mark.parametrize(
    ("source", "message", "line"),
    [
        ("main:\n B LR", "requires a label or immediate target", 1),
        ("main:\n BL R0", "requires a label or immediate target", 1),
        ("main:\n MOV R0, =main", "not code labels", 1),
        ("MOV R0, =later\nlater:\n MOV R1, V0", "not code labels", 0),
        ("const X = 1\nconst X = 2\nmain:\n MOV R0, X", "Duplicate constant", 1),
        ("const X = MISSING\nmain:\n MOV R0, V0", "Undefined constant", 0),
        ("const X = 1 / 0\nmain:\n MOV R0, V0", "Division by zero", 0),
        ("const X = 1 << -1\nmain:\n MOV R0, V0", "non-negative", 0),
        ("const X = 1 << (1 << 100)\nmain:\n MOV R0, V0", "Invalid arithmetic", 0),
        ("const __X = 1\nmain:\n MOV R0, V0", "reserved internal namespace", 0),
        ("const item = 1\nspace:\n item: 1\nmain:\n MOV R0, V0",
         "constant/symbol collision", 2),
        ("space:\n buf: 1048572\nmain:\n MOV R0, V0", "20-bit branch field", 2),
    ],
)
def test_editor_and_assembler_reject_the_same_invalid_source(
    source: str, message: str, line: int
) -> None:
    with pytest.raises(ValueError, match=message):
        assemble(source.splitlines())
    diagnostics = analyze_text(source)["diagnostics"]
    assert any(item["line"] == line and message in item["message"] for item in diagnostics)


def test_analyzer_collects_constant_errors_without_hiding_later_diagnostics() -> None:
    source = "const X = missing\nconst Y = 1 / 0\nmain:\n NOPE R0"
    diagnostics = analyze_text(source)["diagnostics"]
    assert [item["line"] for item in diagnostics] == [0, 1, 3]


@pytest.mark.parametrize("payload", ["[]", "null", '{"text": 42}', "{"])
def test_analyzer_cli_rejects_invalid_payload_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    output = StringIO()
    monkeypatch.setattr(analyzer.sys, "stdin", StringIO(payload))
    monkeypatch.setattr(analyzer.sys, "stdout", output)
    assert analyzer.main() == 1
    result = json.loads(output.getvalue())
    assert result["diagnostics"][0]["code"] == "json"
    assert result["definitions"] == []


def test_analyzer_cli_returns_only_json(monkeypatch: pytest.MonkeyPatch) -> None:
    output = StringIO()
    payload = json.dumps({"text": 'space:\n msg = "CPU"\nmain:\n TEXT V0, V0, msg'})
    monkeypatch.setattr(analyzer.sys, "stdin", StringIO(payload))
    monkeypatch.setattr(analyzer.sys, "stdout", output)
    assert analyzer.main() == 0
    assert json.loads(output.getvalue())["diagnostics"] == []


def test_included_symbols_keep_locations_and_do_not_enter_the_outline(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    weights = data / "weights.de1"
    weights.write_text("# weights\nspace:\n weights = {{1,255,3}}\n", encoding="utf-8")
    shared = data / "shared.de1"
    shared.write_text('const COUNT = 3\ninclude "weights.de1"\n', encoding="utf-8")
    main = tmp_path / "main.de1"
    source = 'include "data/shared.de1"\n output: COUNT\nmain:\n MOV R0, =output\n'
    result = analyze_text(source, main)
    assert result["diagnostics"] == []
    definition = next(item for item in result["definitions"] if item["name"] == "weights")
    assert (definition["path"], definition["line"]) == (str(weights), 2)
    assert [item["name"] for item in result["symbols"]] == ["output", "main"]
    assert set(result["dependencies"]) == {str(shared), str(weights)}
    program = assemble(source.splitlines(), tmp_path)
    inline = assemble("space:\n weights = {{1,255,3}}\n output: 3\nmain:\n MOV R0, =output".splitlines())
    assert program.to_bytes() == inline.to_bytes()
    assert program.symbols["output"] == inline.symbols["output"]


def test_include_errors_use_original_files_and_do_not_hide_root_errors(tmp_path: Path) -> None:
    included = tmp_path / "bad.de1"
    included.write_text('space:\n weights = 102\nmain:\n MOV R0, =later\nlater:\n NOPE R0\n', encoding="utf-8")
    main = tmp_path / "main.de1"
    result = analyze_text('include "bad.de1"\n NOPE R1\n', main)
    locations = {(item["path"], item["line"]) for item in result["diagnostics"]}
    assert locations == {(str(included), 1), (str(included), 3), (str(included), 5), (str(main), 1)}


def test_missing_include_remains_a_dependency_and_recovers(tmp_path: Path) -> None:
    main, weights = tmp_path / "main.de1", tmp_path / "weights.de1"
    source = 'include "weights.de1"\nmain:\n MOV R0, =weights'
    missing = analyze_text(source, main)
    assert missing["dependencies"] == [str(weights)]
    assert missing["diagnostics"][0]["code"] == "include"
    weights.write_text("space:\n weights: 8", encoding="utf-8")
    assert analyze_text(source, main)["diagnostics"] == []
    weights.unlink()
    assert any(item["code"] == "include" for item in analyze_text(source, main)["diagnostics"])


def test_include_overlays_override_disk_and_accept_new_documents(tmp_path: Path) -> None:
    main, weights = tmp_path / "main.de1", tmp_path / "weights.de1"
    weights.write_text("space:\n old_weights: 8", encoding="utf-8")
    source = 'include "weights.de1"\nmain:\n MOV R0, =new_weights'
    overlays = {weights: 'space:\n new_weights: 16\ninclude "extra.de1"',
                tmp_path / "extra.de1": " extra: 1"}
    assert analyze_text(source, main, documents=overlays)["diagnostics"] == []
    assert analyze_text(source, main)["diagnostics"]


def test_include_cycle_and_collisions_are_reported_at_their_origin(tmp_path: Path) -> None:
    main, weights = tmp_path / "main.de1", tmp_path / "weights.de1"
    source = 'include "weights.de1"\n weights: 2\nmain:\n MOV R0, V0'
    weights.write_text('space:\n weights: 1\ninclude "weights.de1"', encoding="utf-8")
    diagnostics = analyze_text(source, main)["diagnostics"]
    assert any(item.get("path") == str(weights) and item["line"] == 2
               and "Circular include" in item["message"] for item in diagnostics)
    assert any(item.get("path") == str(main) and item["line"] == 1
               and "Duplicate data" in item["message"] for item in diagnostics)


def test_data_only_files_are_valid_in_editor_but_not_executable() -> None:
    source = "space:\n weights = {{1,255}}"
    assert analyze_text(source)["diagnostics"] == []
    with pytest.raises(ValueError, match="no instructions"):
        assemble(source.splitlines())


@pytest.mark.parametrize("path", [None, "untitled:Untitled-1", "relative.de1"])
def test_cli_without_file_context_reports_include(
    monkeypatch: pytest.MonkeyPatch, path: str | None,
) -> None:
    output = StringIO()
    monkeypatch.setattr(analyzer.sys, "stdin", StringIO(json.dumps({
        "text": 'include "weights.de1"', "path": path,
    })))
    monkeypatch.setattr(analyzer.sys, "stdout", output)
    assert analyzer.main() == 0
    assert json.loads(output.getvalue())["diagnostics"][0]["code"] == "include"


def test_cli_uses_path_and_open_documents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = StringIO()
    payload = {"path": str(tmp_path / "main.de1"),
               "text": 'include "weights.de1"\nmain:\n MOV R0, =weights',
               "documents": {str(tmp_path / "weights.de1"): "space:\n weights: 8"}}
    monkeypatch.setattr(analyzer.sys, "stdin", StringIO(json.dumps(payload)))
    monkeypatch.setattr(analyzer.sys, "stdout", output)
    assert analyzer.main() == 0
    assert json.loads(output.getvalue())["diagnostics"] == []
