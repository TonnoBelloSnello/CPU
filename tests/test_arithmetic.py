from conftest import MAX_ADDR_VALUE, assert_result, run_simulation

from src.cpu.simulation.runner import run_snapshot


def test_simple_arithmetic() -> None:
    program = [
        "space:",
        "    num1 = 00001010",
        "    num2 = 00000101",
        "main:",
        "MOV R1, [num1]",
        "MOV R2, [num2]",
        "ADD R3, R1, R2",
        "SUB R4, R1, R2",
        "MOV R0, V0",
        "ADD R0, V1"
    ]

    output, _ = run_simulation(program)

    assert "MEM_LOAD: Loaded value 10" in output
    assert "MEM_LOAD: Loaded value 5" in output

    assert_result(output, 15)
    assert_result(output, 5)
    assert_result(output, 1)


def test_reverse_subtract() -> None:
    program = [
        "main:",
        "MOV R0, V5",
        "RSB R1, R0, V20",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 15)


def test_carry_consumers() -> None:
    result = run_snapshot(
        """
        main:
            MOV R0, V0
            MOV R1, V5
            CMP R0, V1
            ADC R2, R1, V3
            SBC R3, R1, V3
            RSC R4, R1, V7
            CMP R1, V0
            ADC R5, R1, V3
            SBC R6, R1, V3
            RSC R7, R1, V7
        """,
        mem_start=0,
        mem_end=4,
    )

    registers = result["registers"]
    assert [registers[f"R{i}"]["dec"] for i in range(2, 8)] == [8, 1, 1, 9, 2, 2]


def test_iverilog_arithmetic_logic_wait() -> None:
    program = [
        "main:",
        "ADD R2, R0, V9",
        "SUB R3, R0, V1",
        "AND R4, R0, V5",
        "ORR R5, R0, V12",
        "EOR R6, R0, V6",
        "WAIT V2",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 9)
    assert_result(output, MAX_ADDR_VALUE)
    assert_result(output, 0)
    assert_result(output, 12)
    assert_result(output, 6)
    assert "WAIT: starting wait for 2 ms (2 cycles)" in output
