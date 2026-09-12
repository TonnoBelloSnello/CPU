from conftest import assert_result, run_simulation


def test_bitwise_operations() -> None:
    program = [
        "space:",
        "    mask = 11110000",
        "    value = 10101010",
        "main:",
        "MOV R1, [mask]",
        "MOV R2, [value]",
        "AND R3, R2, R1",
        "ORR R4, R2, R1",
        "EOR R5, R2, R1",
    ]

    output, _ = run_simulation(program)

    assert "MEM_LOAD: Loaded value 240" in output
    assert "MEM_LOAD: Loaded value 170" in output

    assert_result(output, 160)
    assert_result(output, 250)
    assert_result(output, 90)


def test_bic_operation() -> None:
    program = [
        "main:",
        "MOV R0, V255",
        "MOV R1, V15",
        "BIC R2, R0, R1",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 240)
