import pytest
from conftest import assert_result, run_simulation

HEX_DEST = "HEX display register"


@pytest.mark.parametrize(
    ("program", "hex_results", "register_results"),
    [
        pytest.param(
            ["MOV HEX, V255"],
            (255,),
            (),
            id="mov-immediate-to-hex",
        ),
        pytest.param(
            ["MOV HEX, V0"],
            (0,),
            (),
            id="mov-zero-to-hex",
        ),
        pytest.param(
            [
                "MOV R0, V42",
                "MOV HEX, R0",
            ],
            (42,),
            (42,),
            id="mov-register-to-hex",
        ),
        pytest.param(
            [
                "MOV R0, V100",
                "MOV R1, V55",
                "ADD HEX, R0, R1",
            ],
            (155,),
            (),
            id="add-to-hex",
        ),
        pytest.param(
            [
                "MOV R0, V200",
                "MOV R1, V56",
                "SUB HEX, R0, R1",
            ],
            (144,),
            (),
            id="sub-to-hex",
        ),
        pytest.param(
            [
                "MOV R0, V5",
                "CMP R0, V5",
                "MOVEQ HEX, V99",
            ],
            (99,),
            (),
            id="hex-conditional-write",
        ),
        pytest.param(
            [
                "MOV HEX, V10",
                "MOV HEX, V20",
                "MOV HEX, V30",
            ],
            (10, 20, 30),
            (),
            id="hex-successive-writes",
        ),
        pytest.param(
            [
                "MOV R0, V7",
                "MOV R14, V99",
                "MOV R1, R14",
            ],
            (),
            (99,),
            id="lr-still-writable",
        ),
        pytest.param(
            [
                "MOV LE, V2",
                "MOV HEX, LE",
                "MOV HEX, V1",
                "MOV R0, HEX",
            ],
            (2, 1),
            (1,),
            id="mov-hex-to-register",
        ),
        pytest.param(
            [
                "MOV HEX, V10",
                "MOV R1, V5",
                "ADD R0, R1, HEX",
            ],
            (),
            (15,),
            id="hex-readback-alu",
        ),
        pytest.param(
            [
                "MOV HEX, V42",
                "MOV R14, V99",
                "MOV R0, R14",
            ],
            (),
            (99,),
            id="lr-readable-after-hex-added",
        ),
    ],
)
def test_hex_register_behaviors(
    program: list[str],
    hex_results: tuple[int, ...],
    register_results: tuple[int, ...],
) -> None:
    output, _ = run_simulation(program)

    for value in register_results:
        assert_result(output, value)
    for value in hex_results:
        assert_result(output, value, dest=HEX_DEST)
