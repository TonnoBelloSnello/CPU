import re

from conftest import assert_result, run_simulation


def test_iverilog_branch_and_compare() -> None:
    program = [
        "main:",
        "MOV R0, V5",
        "MOV R1, V5",
        "CMP R0, R1",
        "B skip",
        "MOV R2, V1",
        "skip:",
        "MOV R2, V9",
        "MOV R3, V7",
    ]

    output, labels = run_simulation(program)

    assert "Comparison:" in output
    assert f"BRANCH: Jumping to address {labels['skip']}" in output
    assert_result(output, 9)
    assert_result(output, 7)
    assert re.search(r"Storing result\s+1\b", output) is None


def test_loop_with_branch() -> None:
    program = [
        "main:",
        "MOV R0, V0",
        "MOV R1, V3",
        "loop:",
        "ADD R0, R0, V1",
        "CMP R0, R1",
        "BLT loop",
        "MOV R2, R0",
    ]

    output, _ = run_simulation(program)

    assert "Comparison:" in output
    assert_result(output, 3)


def test_branch_conditions() -> None:
    program = [
        "main:",
        "MOV R0, V10",
        "MOV R1, V20",
        "CMP R0, R1",
        "BLT less_branch",
        "MOV R2, V1",
        "B done",
        "less_branch:",
        "MOV R2, V99",
        "done:",
    ]

    output, labels = run_simulation(program)

    assert f"BRANCH: Jumping to address {labels['less_branch']}" in output
    assert_result(output, 99)


def test_conditional_branch_not_taken() -> None:
    program = [
        "main:",
        "MOV R0, V20",
        "MOV R1, V10",
        "CMP R0, R1",
        "BEQ equal_branch",
        "MOV R2, V42",
        "B done",
        "equal_branch:",
        "MOV R2, V1",
        "done:",
    ]

    output, labels = run_simulation(program)

    assert_result(output, 42)
    assert f"BRANCH: Jumping to address {labels['done']}" in output


def test_branch_reaches_target_above_the_12_bit_field() -> None:
    program = [
        "space:",
        "    pad: 5000",
        "main:",
        "MOV R0, V1",
        "BL far_routine",
        "B done",
        "MOV R0, V99",
        "far_routine:",
        "MOV R0, V7",
        "MOV PC, LR",
        "done:",
        "ADD R1, R0, V1",
    ]

    output, labels = run_simulation(program)

    assert labels["main"] > 0xFFF, "test must place code above the old 12-bit reach"
    assert labels["far_routine"] > 0xFFF
    assert f"BRANCH: Jumping to address {labels['far_routine']}" in output
    assert_result(output, 8)
    assert_result(output, 99, found=False)


def test_wide_branch_splits_target_across_rn_and_rd_fields() -> None:
    from src.cpu.encoder.steps.encoder import encode_asm

    target = 0x9ABC
    [word] = encode_asm(["B far"], {"far": target})

    assert (word >> 26) & 0x3 == 0b11, "branch class"
    assert (word >> 21) & 0xF == 0x0, "BR_B opcode"
    assert word & 0xFFFFF == target
    assert (word >> 16) & 0xF == (target >> 16) & 0xF
    assert (word >> 12) & 0xF == (target >> 12) & 0xF
