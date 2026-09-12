import pytest
from conftest import MAX_ADDR_VALUE, RAM_ADDR_WIDTH, assert_result, run_simulation

from src.cpu.encoder.steps.encoder import encode_asm


@pytest.mark.parametrize(
    ("instructions", "expected"),
    [
        (["MOV R1, V3", "MOV R2, V5", "ADD R0, R1, R2, LSL V2"], 23),
        (["MOV R1, V100", "MOV R2, V32", "ADD R0, R1, R2 LSR V3"], 104),
        (
            ["MOV R2, V0", "SUB R2, R2, V2", "MOV R1, V0", "ADD R0, R1, R2, ASR V1"],
            MAX_ADDR_VALUE,
        ),
        (
            ["MOV R2, V1", "MOV R1, V0", "ORR R0, R1, R2, ROR V1"],
            1 << (RAM_ADDR_WIDTH - 1),
        ),
    ],
    ids=["lsl-arm-comma", "lsr-compact", "asr-sign-extension", "ror-wrap"],
)
def test_shifted_operand2(instructions: list[str], expected: int) -> None:
    output, _ = run_simulation(["main:", *instructions])

    assert_result(output, expected)


@pytest.mark.parametrize(
    ("instructions", "expected"),
    [
        (["MOV R1, V5", "LSL R1, V2"], 20),
        (["MOV R1, V32", "LSR R1, V3"], 4),
        (["MOV R1, V0", "SUB R1, R1, V2", "ASR R1, V1"], MAX_ADDR_VALUE),
    ],
    ids=["lsl-default-rd", "lsr-default-rd", "asr-default-rd"],
)
def test_shift_pseudo_compact_defaults_source_to_destination(
    instructions: list[str], expected: int
) -> None:
    output, _ = run_simulation(["main:", *instructions])

    assert_result(output, expected)


@pytest.mark.parametrize(
    ("operation", "amount"),
    [("LSL", 2), ("LSR", 3), ("ASR", 1), ("ROR", 0)],
    ids=["lsl", "lsr", "asr", "ror"],
)
def test_shift_pseudo_compact_encodes_like_expanded_form(operation: str, amount: int) -> None:
    compact = f"{operation} R1, V{amount}"
    expanded = f"{operation} R1, R1, V{amount}"

    assert encode_asm([compact])[0] == encode_asm([expanded])[0]
