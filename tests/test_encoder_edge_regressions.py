import pytest
from conftest import assert_result, run_simulation

from src.cpu.encoder.steps.encoder import encode_asm, get_register
from src.cpu.encoder.steps.matrix import (
    MatrixTable,
    canonicalize_matrix,
    make_mmul_result_key,
)
from src.cpu.encoder.steps.memory import parse_space_section, prepare_data_section
from src.cpu.encoder.steps.parser import strip_comments
from src.cpu.encoder.steps.prettify import normalize_arm_instructions


@pytest.mark.parametrize(
    "instruction",
    [
        "ADD R0, R1, [value]",
        "CMP R0, [value]",
        "B [value]",
    ],
)
def test_memory_operands_are_rejected_outside_memory_instructions(instruction: str) -> None:
    with pytest.raises(ValueError, match="does not support memory operands"):
        encode_asm([instruction], {"value": 3})


def test_invalid_instruction_aborts_instead_of_returning_encoded_prefix() -> None:
    with pytest.raises(ValueError, match="Invalid operation"):
        encode_asm(["MOV R0, V1", "NOT_AN_OPCODE R1, V9", "MOV R2, V2"])


@pytest.mark.parametrize("token", ["R16", "R999", "R-1", "Rx"])
def test_invalid_registers_are_rejected(token: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid register|out of range"):
        get_register(token)


def test_hex_is_rejected_in_unmarked_rn_field_but_allowed_as_operand2() -> None:
    with pytest.raises(ValueError, match="cannot be encoded in the Rn field"):
        encode_asm(["ADD R0, HEX, R1"])
    with pytest.raises(ValueError, match="cannot be encoded in the Rn field"):
        encode_asm(["CMP HEX, R1"])
    assert encode_asm(["ADD R0, R1, HEX"])


@pytest.mark.parametrize("instruction", ["MOVS R0, V1", "ADDS R0, R1, V2"])
def test_unsupported_s_suffix_is_rejected(instruction: str) -> None:
    with pytest.raises(ValueError, match="Invalid operation"):
        encode_asm([instruction])


def test_negative_immediate_rewrites_preserve_exact_semantics_and_condition() -> None:
    assert normalize_arm_instructions(["ADD R0, V-5"]) == ["SUB R0, R0, V5"]
    assert normalize_arm_instructions(["SUBNE R1, R2, VB-11"]) == ["ADDNE R1, R2, VB11"]
    assert normalize_arm_instructions(["ADC R0, R1, V-5"]) == ["SBC R0, R1, V4"]
    assert normalize_arm_instructions(["SBC R0, R1, V-5"]) == ["ADC R0, R1, V4"]
    assert normalize_arm_instructions(["CMPGT R2, V-7"]) == ["CMNGT R2, V7"]
    assert normalize_arm_instructions(["MOV R3, V-5"]) == ["MVN R3, V4"]
    assert normalize_arm_instructions(["MOV R3, V-0"]) == ["MOV R3, V0"]
    assert normalize_arm_instructions(["ABS R4, V-9"]) == ["ABS R4, V9"]


def test_negative_adc_execution_preserves_the_input_carry() -> None:
    output, _ = run_simulation(
        [
            "main:",
            "MOV R0, V10",
            "CMP R0, V0",
            "ADC R1, R0, V-5",
        ]
    )
    assert_result(output, 6, dest=r"R1\b")


@pytest.mark.parametrize(
    "instruction",
    [
        "AND R0, R1, V-5",
        "RSB R0, R1, V-5",
        "RSC R0, R1, V-5",
        "MUL R0, R1, V-5",
        "TST R0, V-5",
        "SXTB R0, V-5",
    ],
)
def test_unrepresentable_negative_immediates_are_rejected(instruction: str) -> None:
    with pytest.raises(ValueError, match="cannot represent negative immediate"):
        normalize_arm_instructions([instruction])


def test_hash_inside_string_literal_is_not_a_comment() -> None:
    assert strip_comments('msg = "C#" # actual comment') == 'msg = "C#"'
    section = parse_space_section(['msg = "C#" # actual comment'])
    assert section.symbols["msg"] == 0
    assert section.size == 2
    assert bytes(section.memory[index] for index in range(section.size)) == b"C#"


def test_hash_prefixed_shift_amount_is_not_a_comment() -> None:
    line = "LSL R0, R1, #2 # actual comment"
    assert strip_comments(line) == "LSL R0, R1, #2"
    assert encode_asm([line]) == encode_asm(["LSL R0, R1, V2"])
    assert encode_asm(["MOV R0, R1, LSL #2"]) == encode_asm(
        ["MOV R0, R1 LSL V2"]
    )


@pytest.mark.parametrize(
    ("declarations", "message"),
    [
        (["same = 0", "same: 1"], "Duplicate data declaration"),
        (["bad = 102"], "invalid binary value"),
        (["empty ="], "has no value"),
        (["bad:"], "Invalid size"),
        (["__fp16_3C00 = 0"], "reserved internal namespace"),
        (["mmul:thing = 0"], "reserved internal namespace"),
    ],
)
def test_invalid_data_declarations_fail_closed(declarations: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_space_section(declarations)


@pytest.mark.parametrize("name", ["R0", "r15", "SP", "LR", "PC", "LE", "HEX", "V5", "VB101", "F1"])
def test_data_symbols_cannot_shadow_operand_tokens(name: str) -> None:
    with pytest.raises(ValueError, match="reserved operand token"):
        parse_space_section([f"{name} = 00000000"])


def test_matrix_dimensions_and_multiplication_shape_are_validated() -> None:
    sixteen_columns = "{{" + ",".join("1" for _ in range(16)) + "}}"
    sixteen_rows = "{" + ",".join("{1}" for _ in range(16)) + "}"
    with pytest.raises(ValueError, match="dimensions must each be at most 15"):
        prepare_data_section(
            [f"A = {sixteen_columns}", f"B = {sixteen_rows}"],
            ["MUL R0, A, B"],
        )

    with pytest.raises(ValueError, match="Incompatible matrix dimensions"):
        prepare_data_section(
            ["A = {{2, 3}}", "B = {{4}}"],
            ["MUL R0, A, B"],
        )


def test_matrix_descriptor_addresses_must_fit_and_special_destination_is_marked() -> None:
    left = ((2,),)
    right = ((3,),)
    result_key = make_mmul_result_key(left, right)
    matrix_table: MatrixTable = {
        "A": left,
        "B": right,
        canonicalize_matrix(left): left,
        canonicalize_matrix(right): right,
    }

    with pytest.raises(ValueError, match=r"matrix B address.*12-bit SETM"):
        encode_asm(
            ["MUL R0, A, B"],
            {"A": 0, "B": 0x1000, result_key: 2},
            matrix_table,
        )

    words = encode_asm(
        ["MUL HEX, A, B"],
        {"A": 0, "B": 1, result_key: 2},
        matrix_table,
    )
    mmul = words[-1]
    assert (mmul >> 20) & 1 == 1
    assert (mmul >> 12) & 0xF == 14
