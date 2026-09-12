from conftest import MAX_ADDR_VALUE, assert_result, run_simulation


def test_move_operations() -> None:
    program = [
        "main:",
        "MOV R0, V42",
        "MOV R1, R0",
        "MVN R2, V0",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 42)
    assert_result(output, MAX_ADDR_VALUE)
