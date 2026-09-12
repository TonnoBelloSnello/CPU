from conftest import RAM_ADDR_WIDTH, assert_result, run_simulation

from src.cpu.encoder.steps.encoder import encode_asm


def test_branch_class_alu_encoding_fields() -> None:
    abs_word = encode_asm(["ABS R2, V7"])[0]
    max_word = encode_asm(["MAX R3, R1, R2"])[0]
    min_word = encode_asm(["MIN R4, R5, V9"])[0]
    madd_word = encode_asm(["MADD R6, R7, R8"])[0]
    abseq_word = encode_asm(["ABSEQ R1, R2"])[0]

    assert ((abs_word >> 26) & 0b11) == 0b11
    assert ((abs_word >> 25) & 0b1) == 0b1
    assert ((abs_word >> 21) & 0xF) == 0x2
    assert ((abs_word >> 12) & 0xF) == 0x2
    assert (abs_word & 0xFFF) == 0x007

    assert ((max_word >> 26) & 0b11) == 0b11
    assert ((max_word >> 25) & 0b1) == 0b0
    assert ((max_word >> 21) & 0xF) == 0x3
    assert ((max_word >> 16) & 0xF) == 0x1
    assert ((max_word >> 12) & 0xF) == 0x3
    assert (max_word & 0xFFF) == 0x002

    assert ((min_word >> 26) & 0b11) == 0b11
    assert ((min_word >> 25) & 0b1) == 0b1
    assert ((min_word >> 21) & 0xF) == 0x4
    assert ((min_word >> 16) & 0xF) == 0x5
    assert ((min_word >> 12) & 0xF) == 0x4
    assert (min_word & 0xFFF) == 0x009

    assert ((madd_word >> 26) & 0b11) == 0b11
    assert ((madd_word >> 25) & 0b1) == 0b0
    assert ((madd_word >> 21) & 0xF) == 0x5
    assert ((madd_word >> 16) & 0xF) == 0x7
    assert ((madd_word >> 12) & 0xF) == 0x6
    assert (madd_word & 0xFFF) == 0x008

    assert ((abseq_word >> 28) & 0xF) == 0x0
    assert ((abseq_word >> 21) & 0xF) == 0x2


def test_branch_class_alu_ops_execute_without_branch_redirect() -> None:
    neg_seven = (1 << RAM_ADDR_WIDTH) - 7
    program = [
        "main:",
        "MOV R0, V7",
        "RSB R0, R0, V0",
        "ABS R1, R0",
        "MAX R2, R0, V3",
        "MIN R3, R0, V3",
        "MOV R4, V10",
        "MOV R5, V6",
        "MADD R4, R5, V2",
        "ADD R6, R4, V1",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 7)
    assert_result(output, 3)
    assert_result(output, neg_seven)
    assert_result(output, 22)
    assert_result(output, 23)
    assert output.count("BRANCH: Jumping to address") == 1


def test_abs_wraps_on_min_signed_value() -> None:
    min_signed = 1 << (RAM_ADDR_WIDTH - 1)
    program = [
        "main:",
        "MOV R0, V1",
        "LSL R0, R0, V15",
        "ABS R1, R0",
    ]

    output, _ = run_simulation(program)

    assert_result(output, min_signed)


def test_branch_class_alu_condition_codes() -> None:
    program = [
        "main:",
        "MOV R0, V0",
        "MOV R1, V4",
        "CMP R0, V0",
        "MADDEQ R1, R1, V2",
        "MADDNE R1, R1, V2",
        "MOV R2, V1",
        "CMP R0, V1",
        "MAXNE R2, R2, V7",
        "MINNE R3, R2, V5",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 12)
    assert_result(output, 7)
    assert_result(output, 5)
    assert "Condition not met (cond=1), skipping instruction" in output
