import pytest
from conftest import assert_result, run_simulation


@pytest.mark.parametrize(
    ("instructions", "expected"),
    [
        (
            ["MOV R0, vb1010", "MOV R1, vb11111111", "MOV R2, vb1"],
            (10, 255, 1),
        ),
        (["MOV R0, vb1010", "ADD R1, R0, vb101"], (15,)),
        (["MOV R0, vb10100", "SUB R1, R0, vb1010"], (10,)),
        (
            ["MOV R0, vb1010", "ADD R1, R0, v5", "SUB R2, R1, vb101"],
            (15, 10),
        ),
        (["MOV R0, vb1010", "CMP R0, vb1010", "MOVEQ R1, v1"], (1,)),
    ],
    ids=[
        "mov-binary-literals",
        "add-binary-operand2",
        "sub-binary-operand2",
        "mixed-binary-decimal",
        "compare-binary",
    ],
)
def test_binary_values(instructions: list[str], expected: tuple[int, ...]) -> None:
    output, _ = run_simulation(["main:", *instructions])

    for value in expected:
        assert_result(output, value)
