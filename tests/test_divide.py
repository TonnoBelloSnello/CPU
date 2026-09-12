import re

import pytest
from conftest import assert_result, run_simulation

from src.cpu.encoder.steps.encoder import encode_asm


@pytest.mark.parametrize(
    ("operand2", "immediate_bit"),
    [("V3", 1), ("R3", 0)],
    ids=["immediate-operand2", "register-operand2"],
)
def test_div_encoding(operand2: str, immediate_bit: int) -> None:
    word = encode_asm([f"DIV R2, R1, {operand2}"])[0]

    assert ((word >> 26) & 0b11) == 0b01
    assert ((word >> 25) & 0b1) == immediate_bit
    assert ((word >> 21) & 0xF) == 0xF
    assert ((word >> 16) & 0xF) == 0x1
    assert ((word >> 12) & 0xF) == 0x2
    assert (word & 0xFFF) == 0x003


def test_div_register_operands() -> None:
    program = [
        "main:",
        "MOV R1, V84",
        "MOV R2, V7",
        "DIV R3, R1, R2",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 12)
    assert "DIV: 84 / 7 = 12" in output


def test_div_immediate_operand() -> None:
    program = [
        "main:",
        "MOV R1, V99",
        "DIV R2, R1, V9",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 11)


def test_div_two_operand_shorthand() -> None:
    program = [
        "main:",
        "MOV R0, V100",
        "DIV R0, V4",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 25)


def test_div_by_zero_writes_zero() -> None:
    program = [
        "main:",
        "MOV R1, V77",
        "DIV R2, R1, V0",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 0)
    assert "divide-by-zero" in output


def test_div_across_operand_magnitudes() -> None:
    program = [
        "main:",
        "MOV R0, V4095",
        "MUL R1, R0, V16",
        "ADD R1, R1, V15",
        "MOV R3, V255",
        "MOV R4, V84",
        "DIV R2, R1, V3",
        "DIV R2, R1, R3",
        "DIV R2, R1, R0",
        "DIV R2, R1, R1",
        "DIV R2, R0, R1",
        "DIV R2, R0, V1",
        "DIV R2, R4, V7",
        "DIV R2, R3, V16",
    ]

    output, _ = run_simulation(program)

    for dividend, divisor, quotient in [
        (65535, 3, 21845),
        (65535, 255, 257),
        (65535, 4095, 16),
        (65535, 65535, 1),
        (4095, 65535, 0),
        (4095, 1, 4095),
        (84, 7, 12),
        (255, 16, 15),
    ]:
        assert f"DIV: {dividend} / {divisor} = {quotient}" in output, (
            f"Wrong quotient for {dividend} / {divisor}"
        )



def test_div_conditional_execution() -> None:
    program = [
        "main:",
        "MOV R0, V0",
        "MOV R1, V84",
        "MOV R2, V7",
        "CMP R0, V0",
        "DIVEQ R3, R1, R2",
        "DIVNE R4, R1, R2",
        "CMP R0, V1",
        "DIVNE R5, R1, R2",
    ]

    output, _ = run_simulation(program)

    assert len(re.findall(r"Storing result\s+12\b", output)) >= 2
    assert "Condition not met (cond=1), skipping instruction" in output
