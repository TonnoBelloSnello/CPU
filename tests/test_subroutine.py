from conftest import assert_result, run_simulation


def test_subroutine_call_bl() -> None:
    program = [
        "main:",
        "MOV R0, V5",
        "BL multiply_by_two",
        "MOV R2, R0",
        "B end",
        "multiply_by_two:",
        "ADD R0, R0, R0",
        "MOV PC, R14",
        "end:",
    ]

    output, labels = run_simulation(program)

    assert "BL: Saving PC=" in output
    assert f"BRANCH: Jumping to address {labels['multiply_by_two']}" in output
    assert_result(output, 10)
