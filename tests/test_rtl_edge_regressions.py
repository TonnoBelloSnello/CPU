import pytest
from conftest import assert_result, run_simulation


def test_pop_sp_exposes_post_increment_with_and_without_a_bubble() -> None:
    output, _ = run_simulation(
        [
            "main:",
            "MOV SP, V256",
            "MOV R0, V77",
            "PUSH R0",
            "POP SP",
            "MOV R1, SP",
            "WAIT V0",
            "MOV R2, SP",
        ]
    )

    assert "STACK_POP: Loaded value 77" in output
    assert_result(output, 256, dest=r"R1\b")
    assert_result(output, 256, dest=r"R2\b")


def test_pop_display_registers_forward_the_updated_sp_immediately() -> None:
    output, _ = run_simulation(
        [
            "main:",
            "MOV SP, V256",
            "MOV R0, V77",
            "PUSH R0",
            "POP LE",
            "MOV R1, SP",
            "PUSH R0",
            "POP HEX",
            "MOV R2, SP",
        ]
    )

    assert "into LE (LEDR)" in output
    assert "into HEX display register" in output
    assert_result(output, 256, dest=r"R1\b")
    assert_result(output, 256, dest=r"R2\b")


def test_le_and_hex_are_valid_register_indirect_memory_addresses() -> None:
    output, symbols = run_simulation(
        [
            "space:",
            "    source_le = 00101010",
            "    source_hex = 00110111",
            "    target_le: 2",
            "    target_hex: 2",
            "main:",
            "MOV LE, source_le",
            "MOV HEX, source_hex",
            "MOV R0, [LE]",
            "MOV R1, [HEX]",
            "MOV LE, target_le",
            "MOV HEX, target_hex",
            "SAVE R1, [LE]",
            "SAVE R0, [HEX]",
            "MOV R2, [target_le]",
            "MOV R3, [target_hex]",
            "MOV R4, R0",
            "MOV R5, R1",
            "MOV R6, R2",
            "MOV R7, R3",
        ]
    )

    assert f"from address {symbols['source_le']} into R0" in output
    assert f"from address {symbols['source_hex']} into R1" in output
    assert f"at address {symbols['target_le']}" in output
    assert f"at address {symbols['target_hex']}" in output
    assert_result(output, 42, dest=r"R4\b")
    assert_result(output, 55, dest=r"R5\b")
    assert_result(output, 55, dest=r"R6\b")
    assert_result(output, 42, dest=r"R7\b")


def test_hex_is_consumed_as_hex_by_stack_store_and_madd() -> None:
    output, _ = run_simulation(
        [
            "space:",
            "    byte_out: 1",
            "    wide_out: 2",
            "main:",
            "MOV SP, V256",
            "MOV LR, V10",
            "MOV HEX, V20",
            "PUSH HEX",
            "POP R0",
            "SAVE HEX, [byte_out]",
            "MOV R1, [byte_out]",
            "SAVEM HEX, [wide_out]",
            "MOVM R2, [wide_out]",
            "MOV R3, V2",
            "MADD HEX, R3, V3",
            "MOV R4, HEX",
            "MOV R5, R0",
            "MOV R6, R1",
            "MOV R7, R2",
        ]
    )

    assert "STACK_PUSH: Stored value 20" in output
    assert "MEM_STORE: Stored value 20" in output
    assert "MEM_STORE_MULTI: Stored value 20" in output
    assert_result(output, 26, dest="HEX display register")
    assert_result(output, 26, dest=r"R4\b")
    assert_result(output, 20, dest=r"R5\b")
    assert_result(output, 20, dest=r"R6\b")
    assert_result(output, 20, dest=r"R7\b")


@pytest.mark.parametrize(
    ("destination", "log_destination"),
    [
        ("LE", r"LE \(LEDR\)"),
        ("HEX", "HEX display register"),
    ],
)
def test_mmul_writes_display_register_destinations(destination: str, log_destination: str) -> None:
    result_key = "mmul:{{0,0},{0,0}}:{{0,0},{0,0}}"
    output, symbols = run_simulation(
        [
            "space:",
            "    A = {{0, 0}, {0, 0}}",
            "    B = {{0, 0}, {0, 0}}",
            "main:",
            f"MUL {destination}, A, B",
            f"MOV R0, {destination}",
        ]
    )

    result_address = symbols[result_key]
    assert_result(output, result_address, dest=log_destination)
    assert_result(output, result_address, dest=r"R0\b")


def test_mmul_pc_destination_redirects_through_normal_writeback() -> None:
    result_key = "mmul:{{0,0},{0,0}}:{{0,0},{0,0}}"
    output, symbols = run_simulation(
        [
            "space:",
            "    A = {{0, 0}, {0, 0}}",
            "    B = {{0, 0}, {0, 0}}",
            "main:",
            "MUL PC, A, B",
            "MOV R0, V99",
        ]
    )

    result_address = symbols[result_key]
    assert result_address % 4 == 0
    assert_result(output, result_address, dest="in PC")
    assert_result(output, 99, dest=r"R0\b", found=False)
