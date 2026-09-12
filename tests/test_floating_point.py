import math
import re

from conftest import assert_register, run_simulation

from src.cpu.encoder.steps.fp16 import (
    FP16_QUIET_NAN,
    float_to_fp16_bits,
    fp16_bits_to_float,
    fp16_literal_info,
    fp16_literal_key_from_bits,
    parse_fp_literal,
)


def _assert_mem_load_multi(output: str, register: int, value: int) -> None:
    pattern = rf"MEM_LOAD_MULTI: Loaded value\s+{value}\b.*\bR{register}\b"
    assert re.search(pattern, output) is not None, (
        f"Expected MOVM-style load missing: R{register} = {value}"
    )


def test_parse_fp_literal_accepts_supported_formats() -> None:
    assert parse_fp_literal("F1.5") == 1.5
    assert parse_fp_literal("f-0.25") == -0.25
    assert parse_fp_literal("F1e2") == 100.0
    assert parse_fp_literal("F+inf") == float("inf")
    parsed_nan = parse_fp_literal("FNaN")
    assert parsed_nan is not None
    assert math.isnan(parsed_nan)


def test_parse_fp_literal_rejects_invalid_formats() -> None:
    assert parse_fp_literal("1.5") is None
    assert parse_fp_literal("F") is None
    assert parse_fp_literal("Fx1") is None
    assert parse_fp_literal("F1_5") is None


def test_fp16_helpers_cover_specials_and_canonical_literal_keys() -> None:
    assert float_to_fp16_bits(float("nan")) == FP16_QUIET_NAN
    assert float_to_fp16_bits(float("inf")) == 0x7C00
    assert float_to_fp16_bits(float("-inf")) == 0xFC00
    assert float_to_fp16_bits(1e10) == 0x7C00
    assert float_to_fp16_bits(-1e10) == 0xFC00

    bits_35 = float_to_fp16_bits(3.5)
    assert bits_35 == 0x4300
    assert fp16_bits_to_float(bits_35) == 3.5

    nan_info = fp16_literal_info("Fnan")
    nan_key, nan_bits = nan_info if nan_info is not None else (None, None)
    assert nan_bits == FP16_QUIET_NAN
    assert nan_key == fp16_literal_key_from_bits(FP16_QUIET_NAN)


def test_fp_register_arithmetic_roundtrip() -> None:
    value_a = 1.5
    value_b = 2.25
    bits_a = float_to_fp16_bits(value_a)
    bits_b = float_to_fp16_bits(value_b)
    bits_add = float_to_fp16_bits(value_a + value_b)
    bits_sub = float_to_fp16_bits((value_a + value_b) - value_a)
    bits_mul = float_to_fp16_bits(value_a * value_b)
    bits_div = float_to_fp16_bits((value_a * value_b) / value_a)

    program = [
        "space:",
        "    a = F1.5",
        "    b = F2.25",
        "main:",
        "MOVM R1, [a]",
        "MOVM R2, [b]",
        "FADD R3, R1, R2",
        "FSUB R4, R3, R1",
        "FMUL R5, R1, R2",
        "FDIV R6, R5, R1",
    ]

    output, _ = run_simulation(program)

    _assert_mem_load_multi(output, 1, bits_a)
    _assert_mem_load_multi(output, 2, bits_b)
    assert_register(output, 3, bits_add)
    assert_register(output, 4, bits_sub)
    assert_register(output, 5, bits_mul)
    assert_register(output, 6, bits_div)
    assert "FP ALU opcode=" in output


def test_fdiv_matches_reference_across_values() -> None:
    pairs = [
        (1.0, 3.0),
        (1.0, 7.0),
        (3.5, 1.25),
        (100.0, 3.0),
        (0.5, 4.0),
        (5.0, 5.0),
        (1.0, 1024.0),
        (2.0, 3.0),
    ]

    program = ["main:"]
    expected: list[tuple[int, int]] = []
    for index, (numerator, denominator) in enumerate(pairs):
        register = 2 + (index % 4)
        program += [
            f"FMOV R0, F{numerator}",
            f"FMOV R1, F{denominator}",
            "MOV R7, V0",
            f"FDIV R{register}, R0, R1",
        ]
        exact = fp16_bits_to_float(float_to_fp16_bits(numerator)) / \
            fp16_bits_to_float(float_to_fp16_bits(denominator))
        expected.append((register, float_to_fp16_bits(exact)))

    output, _ = run_simulation(program)

    for (register, bits), (numerator, denominator) in zip(expected, pairs, strict=True):
        pattern = rf"Storing result\s+{bits}\b.*\bR{register}\b"
        assert re.search(pattern, output) is not None, (
            f"FDIV {numerator} / {denominator} did not produce {bits} in R{register}"
        )



def test_fsub_cancellation_normalises() -> None:
    pairs = [
        (1.0, 0.99951171875),
        (1.0, 0.9990234375),
        (1.0, 0.998046875),
        (1.0, 0.99609375),
        (1.0, 0.9921875),
        (1.0, 0.984375),
        (1.0, 0.96875),
        (1.0, 0.9375),
        (1.0, 0.875),
        (1.0, 0.75),
        (1.0, 0.5),
        (1024.0, 1023.5),
        (2.0, 1.9990234375),
    ]

    program = ["main:"]
    expected: list[tuple[int, int]] = []
    for index, (left, right) in enumerate(pairs):
        register = 2 + (index % 4)
        program += [
            f"FMOV R0, F{left}",
            f"FMOV R1, F{right}",
            "MOV R7, V0",
            f"FSUB R{register}, R0, R1",
        ]
        difference = fp16_bits_to_float(float_to_fp16_bits(left)) - \
            fp16_bits_to_float(float_to_fp16_bits(right))
        expected.append((register, float_to_fp16_bits(difference)))

    output, _ = run_simulation(program)

    for (register, bits), (left, right) in zip(expected, pairs, strict=True):
        pattern = rf"Storing result\s+{bits}\b.*\bR{register}\b"
        assert re.search(pattern, output) is not None, (
            f"FSUB {left} - {right} did not produce {bits} in R{register}"
        )



def test_fdiv_underflow_flushes_to_zero() -> None:
    program = [
        "main:",
        "FMOV R0, F1.0",
        "FMOV R1, F65504.0",
        "MOV R7, V0",
        "FDIV R2, R0, R1",
    ]

    output, _ = run_simulation(program)

    assert_register(output, 2, 0)


def test_fp_immediate_literals_are_deduplicated() -> None:
    bits_pos = float_to_fp16_bits(1.5)
    bits_neg = float_to_fp16_bits(-0.5)
    bits_sum = float_to_fp16_bits(3.0)
    bits_mul = float_to_fp16_bits(-0.75)

    key_pos = fp16_literal_key_from_bits(bits_pos)
    key_neg = fp16_literal_key_from_bits(bits_neg)

    program = [
        "main:",
        "FMOV R0, F1.5",
        "FADD R1, R0, F1.5",
        "FSUB R2, R1, F1.5",
        "FMUL R3, R2, F-0.5",
    ]

    output, symbols = run_simulation(program)

    fp_keys = [name for name in symbols if name.startswith("__fp16_")]
    assert key_pos in symbols
    assert key_neg in symbols
    assert len(fp_keys) == 2
    assert symbols[key_pos] != symbols[key_neg]

    assert_register(output, 0, bits_pos)
    assert_register(output, 1, bits_sum)
    assert_register(output, 2, bits_pos)
    assert_register(output, 3, bits_mul)
    assert "FMOV (imm)" in output
    assert "FP ALU (imm) opcode=" in output


def test_fcmp_drives_conditional_moves_for_eq_lt_and_unordered() -> None:
    program = [
        "main:",
        "FMOV R0, F1.25",
        "FMOV R1, F1.25",
        "FCMP R0, R1",
        "MOVEQ R2, V1",
        "MOVNE R3, V1",
        "FCMP R0, F2.0",
        "MOVLT R4, V1",
        "MOVGE R5, V1",
        "FMOV R6, FNaN",
        "FCMP R6, R0",
        "MOVVS R7, V1",
        "MOVVC R8, V1",
    ]

    output, _ = run_simulation(program)

    assert_register(output, 2, 1)
    assert_register(output, 3, 1, found=False)
    assert_register(output, 4, 1)
    assert_register(output, 5, 1, found=False)
    assert_register(output, 7, 1)
    assert_register(output, 8, 1, found=False)
    assert output.count("FP Compare:") >= 3


def test_space_float_initializer_is_little_endian_and_usable() -> None:
    bits = float_to_fp16_bits(3.5)
    low_byte = bits & 0xFF
    high_byte = (bits >> 8) & 0xFF
    bits_sum = float_to_fp16_bits(4.5)

    program = [
        "space:",
        "    value = F3.5",
        "main:",
        "MOV R0, [value]",
        "MOV R1, value",
        "ADD R1, R1, V1",
        "MOV R2, [R1]",
        "MOVM R3, [value]",
        "FADD R4, R3, F1.0",
    ]

    output, symbols = run_simulation(program)

    assert symbols["value"] >= 4
    assert f"MEM_LOAD: Loaded value {low_byte}" in output
    assert f"MEM_LOAD: Loaded value {high_byte}" in output
    _assert_mem_load_multi(output, 3, bits)
    assert_register(output, 4, bits_sum)
