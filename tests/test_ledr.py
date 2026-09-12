import re

import pytest
from conftest import assert_result, run_simulation

LE_DEST = r"LE \(LEDR\)"


@pytest.mark.parametrize(
    ("program", "le_results", "register_results", "absent_patterns"),
    [
        pytest.param(
            ["MOV LE, V10"],
            (10,),
            (),
            (),
            id="mov-immediate-to-le",
        ),
        pytest.param(
            [
                "MOV LE, V5",
                "MOV R0, V10",
                "MOV LE, R0",
            ],
            (5, 10),
            (),
            (),
            id="mov-le-led-pattern",
        ),
        pytest.param(
            [
                "MOV R0, V7",
                "MOV LE, R0",
            ],
            (7,),
            (7,),
            (),
            id="mov-register-to-le",
        ),
        pytest.param(
            [
                "MOV LE, V13",
                "MOV R0, LE",
            ],
            (13,),
            (13,),
            (),
            id="mov-le-to-register",
        ),
        pytest.param(
            [
                "MOV R0, V6",
                "MOV R1, V3",
                "ADD LE, R0, R1",
            ],
            (9,),
            (),
            (),
            id="add-to-le",
        ),
        pytest.param(
            [
                "MOV R0, V15",
                "MOV R1, V5",
                "SUB LE, R0, R1",
            ],
            (10,),
            (),
            (),
            id="sub-to-le",
        ),
        pytest.param(
            [
                "MOV LE, V8",
                "ADD R0, LE, V4",
            ],
            (8,),
            (12,),
            (),
            id="le-as-alu-source",
        ),
        pytest.param(
            [
                "MOV LE, V3",
                "MOV R1, V7",
                "ADD R0, R1, LE",
            ],
            (3,),
            (10,),
            (),
            id="le-as-second-operand",
        ),
        pytest.param(
            [
                "MOV LE, V5",
                "MOV R0, V3",
                "ADD LE, LE, R0",
            ],
            (5, 8),
            (),
            (),
            id="add-le-to-itself",
        ),
        pytest.param(
            [
                "MOV R0, V15",
                "MOV R1, V10",
                "AND LE, R0, R1",
            ],
            (10,),
            (),
            (),
            id="le-with-bitwise-and",
        ),
        pytest.param(
            [
                "MOV R0, V5",
                "MOV R1, V10",
                "ORR LE, R0, R1",
            ],
            (15,),
            (),
            (),
            id="le-with-orr",
        ),
        pytest.param(
            [
                "MOV R0, V5",
                "MOV LE, V7",
                "B end",
                "MOV R0, V99",
                "end:",
                "MOV R1, V1",
            ],
            (7,),
            (1,),
            (r"Storing result\s+99\b",),
            id="pc-write-not-affected-by-le",
        ),
        pytest.param(
            [
                "MOV LE, V255",
                "MOV R0, V42",
            ],
            (255,),
            (42,),
            (),
            id="le-separate-from-pc",
        ),
        pytest.param(
            [
                "MOV LE, V0",
                "MOV R0, V5",
                "MOV R1, V3",
                "CMP R0, R1",
                "MOVNE LE, V9",
            ],
            (0, 9),
            (),
            (),
            id="le-with-conditional-mov",
        ),
        pytest.param(
            [
                "MOV LE, V4",
                "MOV R0, V5",
                "MOV R1, V3",
                "CMP R0, R1",
                "MOVEQ LE, V99",
                "MOV R2, V1",
            ],
            (4,),
            (1,),
            (r"Storing result\s+99\b.*\bLE",),
            id="le-conditional-skipped",
        ),
    ],
)
def test_le_register_behaviors(
    program: list[str],
    le_results: tuple[int, ...],
    register_results: tuple[int, ...],
    absent_patterns: tuple[str, ...],
) -> None:
    output, _ = run_simulation(program)

    for value in register_results:
        assert_result(output, value)
    for value in le_results:
        assert_result(output, value, dest=LE_DEST)
    for pattern in absent_patterns:
        assert re.search(pattern, output) is None
