from conftest import assert_result, run_simulation


def test_mul_register() -> None:
    program = [
        "main:",
        "MOV R1, V7",
        "MOV R2, V6",
        "MUL R3, R1, R2",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 42)


def test_mul_immediate() -> None:
    program = [
        "main:",
        "MOV R0, V9",
        "MUL R1, R0, V5",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 45)
