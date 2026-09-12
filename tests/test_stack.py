import re

from conftest import MAX_ADDR_VALUE, assert_result, run_simulation


def test_stack_push_pop_lifo() -> None:
    program = [
        "main:",
        "MOV R13, V256",
        "MOV R0, V10",
        "MOV R1, V20",
        "MOV R2, V30",
        "PUSH R0",
        "PUSH R1",
        "PUSH R2",
        "POP R3",
        "POP R4",
        "POP R5",
    ]

    output, _ = run_simulation(program)

    assert "STACK_PUSH: Stored value 10" in output
    assert "STACK_PUSH: Stored value 20" in output
    assert "STACK_PUSH: Stored value 30" in output
    assert "address 254" in output
    assert "address 252" in output
    assert "address 250" in output

    assert "STACK_POP: Loaded value 30" in output
    assert "STACK_POP: Loaded value 20" in output
    assert "STACK_POP: Loaded value 10" in output


def test_stack_pop_restores_sp() -> None:
    program = [
        "main:",
        "MOV R2, R13",
        "MOV R0, V42",
        "PUSH R0",
        "POP R1",
        "SUB R3, R13, R2",
    ]

    output, _ = run_simulation(program)

    assert "STACK_PUSH: Stored value 42" in output
    assert "STACK_POP: Loaded value 42" in output
    assert_result(output, 0)


def test_stack_recursive_function() -> None:
    program = [
        "main:",
        "MOV R0, V4",
        "BL fact",
        "MOV R1, R0",
        "B done",
        "fact:",
        "CMP R0, V1",
        "BEQ base",
        "PUSH LR",
        "PUSH R0",
        "SUB R0, R0, V1",
        "BL fact",
        "POP R2",
        "POP LR",
        "MUL R0, R0, R2",
        "MOV PC, LR",
        "base:",
        "MOV R0, V1",
        "MOV PC, LR",
        "done:",
    ]

    output, _ = run_simulation(program)

    assert "STACK_PUSH" in output
    assert "STACK_POP" in output
    assert_result(output, 24)


def test_stack_preserves_full_register_width() -> None:
    program = [
        "main:",
        "MOV R13, V256",
        "MOV R0, V300",
        "PUSH R0",
        "POP R1",
        "ADD R2, R1, V0",
    ]

    output, _ = run_simulation(program)

    assert "STACK_PUSH: Stored value 300" in output
    assert "STACK_POP: Loaded value 300" in output
    assert_result(output, 300)


def test_stack_default_sp_init() -> None:
    program = [
        "main:",
        "MOV R0, V1",
        "PUSH R0",
        "POP R1",
        "ADD R2, R1, V0",
    ]

    output, _ = run_simulation(program)

    assert "STACK_PUSH: Stored value 1" in output
    match = re.search(r"STACK_PUSH:.* at address (\d+)", output)
    assert match is not None, "Missing stack address output"
    assert int(match.group(1)) > MAX_ADDR_VALUE - 5000
    assert "STACK_POP: Loaded value 1" in output
    assert_result(output, 1)


def test_push_pop_register_list_round_trips() -> None:
    program = [
        "main:",
        "MOV R13, V256",
        "MOV R4, V1000",
        "MOV R5, V2000",
        "MOV R6, V3000",
        "PUSH {R4-R6}",
        "MOV R4, V0",
        "MOV R5, V0",
        "MOV R6, V0",
        "POP {R4-R6}",
        "ADD R0, R4, V0",
        "ADD R1, R5, V0",
        "ADD R2, R6, V0",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 1000, dest=r"R0\b")
    assert_result(output, 2000, dest=r"R1\b")
    assert_result(output, 3000, dest=r"R2\b")


def test_push_register_list_puts_lowest_register_at_lowest_address() -> None:
    program = [
        "main:",
        "MOV R13, V256",
        "MOV R4, V11",
        "MOV R5, V22",
        "PUSH {R4, R5}",
        "MOV R0, V252",
        "MOVM R1, [R0]",
        "MOV R0, V254",
        "MOVM R2, [R0]",
        "ADD R6, R1, V0",
        "ADD R7, R2, V0",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 11, dest=r"R6\b")
    assert_result(output, 22, dest=r"R7\b")


def test_nested_calls_survive_a_register_list_prologue() -> None:
    program = [
        "main:",
        "MOV R0, V3",
        "BL outer",
        "ADD R1, R0, V0",
        "B done",
        "outer:",
        "PUSH {R4, LR}",
        "MOV R4, R0",
        "BL inner",
        "ADD R0, R0, R4",
        "POP {R4, PC}",
        "inner:",
        "MOV R0, V10",
        "MOV PC, LR",
        "done:",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 13, dest=r"R1\b")


def test_register_list_rejects_a_duplicate_entry() -> None:
    import pytest

    from src.cpu.encoder.steps.encoder import encode_asm

    with pytest.raises(ValueError, match="listed twice"):
        encode_asm(["PUSH {R4, R4}"])
