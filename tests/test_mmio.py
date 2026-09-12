from conftest import RAM_ADDR_WIDTH, assert_result, run_simulation

MMIO_BASE = (1 << RAM_ADDR_WIDTH) - 256
MMIO_OFF_LED = 0x00
MMIO_OFF_HEX = 0x04
MMIO_OFF_KEYS = 0x08
MMIO_OFF_CYCLES_LO = 0x0C


def _load_window_base(register: str) -> list[str]:
    return [f"MOV {register}, V{MMIO_BASE >> 8}", f"LSL {register}, V8"]


def test_store_to_led_slot_drives_the_le_register() -> None:
    program = [
        "main:",
        *_load_window_base("R0"),
        "MOV R1, V682",
        "SAVEM R1, [R0]",
        "MOV R2, LE",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 682, dest=r"R2\b")


def test_le_written_by_the_isa_reads_back_through_the_window() -> None:
    program = [
        "main:",
        "MOV LE, V123",
        *_load_window_base("R0"),
        "MOVM R1, [R0]",
        "ADD R2, R1, V0",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 123, dest=r"R2\b")


def test_hex_slot_round_trips_through_the_window() -> None:
    program = [
        "main:",
        *_load_window_base("R0"),
        f"ADD R0, R0, V{MMIO_OFF_HEX}",
        "MOV R1, V4095",
        "SAVEM R1, [R0]",
        "MOVM R2, [R0]",
        "ADD R3, R2, V0",
        "MOV R4, HEX",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 4095, dest=r"R3\b")
    assert_result(output, 4095, dest=r"R4\b")


def test_byte_store_merges_into_the_live_display_register() -> None:
    program = [
        "main:",
        "MOV R1, V4095",
        "MOV LE, R1",
        *_load_window_base("R0"),
        "MOV R2, V16",
        "SAVE R2, [R0]",
        "MOV R3, LE",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 0x0F10, dest=r"R3\b")


def test_keys_slot_reads_zero_when_no_key_is_pressed() -> None:
    program = [
        "main:",
        *_load_window_base("R0"),
        f"ADD R0, R0, V{MMIO_OFF_KEYS}",
        "MOVM R1, [R0]",
        "MOV R2, V7",
        "CMP R1, V0",
        "MOVEQ R2, V1",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 1, dest=r"R2\b")


def test_cycle_counter_slot_is_running() -> None:
    program = [
        "main:",
        *_load_window_base("R0"),
        f"ADD R0, R0, V{MMIO_OFF_CYCLES_LO}",
        "MOVM R1, [R0]",
        "MOVM R2, [R0]",
        "MOV R3, V0",
        "CMP R1, V0",
        "MOVNE R3, V1",
        "MOV R4, V0",
        "CMP R2, R1",
        "MOVHI R4, V1",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 1, dest=r"R3\b")
    assert_result(output, 1, dest=r"R4\b")


def test_unmapped_slot_reads_zero() -> None:
    program = [
        "main:",
        *_load_window_base("R0"),
        "ADD R0, R0, V128",
        "MOVM R1, [R0]",
        "MOV R2, V7",
        "CMP R1, V0",
        "MOVEQ R2, V1",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 1, dest=r"R2\b")


def test_stack_lives_below_the_window_and_survives_peripheral_traffic() -> None:
    program = [
        "main:",
        "MOV R5, V1234",
        "PUSH R5",
        *_load_window_base("R0"),
        "MOV R1, V999",
        "SAVEM R1, [R0]",
        "POP R6",
        "ADD R7, R6, V0",
    ]

    output, _ = run_simulation(program)

    assert_result(output, 1234, dest=r"R7\b")
