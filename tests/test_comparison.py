from conftest import assert_result, run_simulation


def test_conditional_execution() -> None:
    program = [
        "main:",
        "MOV R1, V20",
        "MOV R2, V10",
        "CMP R1, R2",
        "SUBGT R3, R1, R2",
    ]

    output, _ = run_simulation(program)

    assert "Comparison:" in output
    assert_result(output, 10)


def test_comparison_instructions() -> None:
    program = [
        "main:",
        "MOV R0, V10",
        "MOV R1, V10",
        "CMP R0, R1",
        "MOV R2, V5",
        "CMN R2, V5",
        "TST R0, V8",
    ]

    output, _ = run_simulation(program)

    assert output.count("Comparison:") == 3
