from conftest import assert_result, run_simulation


def test_wait_instruction() -> None:
    program = [
        "main:",
        "MOV R0, V1",
        "WAIT V5",
        "MOV R1, V2",
    ]
    output, _ = run_simulation(program)

    assert "WAIT: starting wait for 5 ms (5 cycles)" in output
    assert_result(output, 1)
    assert_result(output, 2)
