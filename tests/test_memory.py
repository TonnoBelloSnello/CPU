from conftest import MAX_ADDR_VALUE, RAM_ADDR_WIDTH, assert_result, run_simulation


def test_memory_address_load() -> None:
    program = [
        "space:",
        "    first_var = 00000100",
        "    second_var = 11111111",
        "main:",
        "MOV R1, first_var",
        "MOV R2, second_var",
        "MOV R3, [first_var]",
        "MOV R4, [second_var]",
    ]

    output, symbols = run_simulation(program)

    assert_result(output, symbols['first_var'])
    assert_result(output, symbols['second_var'])

    assert "MEM_LOAD: Loaded value 4" in output
    assert "MEM_LOAD: Loaded value 255" in output


def test_memory_uninitialized_defaults_to_zero() -> None:
    program = [
        "space:",
        "    sentinel = 00000001",
        "    buffer: 3",
        "main:",
        "MOV R0, buffer",
        "MOV R1, [buffer]",
        "ADD R2, R1, V1",
    ]

    output, symbols = run_simulation(program)

    assert symbols["buffer"] == symbols["sentinel"] + 1
    assert_result(output, symbols["buffer"])
    assert f"MEM_LOAD: Reading from address {symbols['buffer']}" in output
    assert "MEM_LOAD: Loaded value 0" in output
    assert_result(output, 1)


def test_memory_load_values_feed_alu() -> None:
    program = [
        "space:",
        "    a = 00000011",
        "    b = 00000101",
        "main:",
        "MOV R0, [a]",
        "MOV R1, [b]",
        "ADD R2, R0, R1",
    ]

    output, symbols = run_simulation(program)

    assert f"MEM_LOAD: Reading from address {symbols['a']} into R0" in output
    assert f"MEM_LOAD: Reading from address {symbols['b']} into R1" in output
    assert "MEM_LOAD: Loaded value 3" in output
    assert "MEM_LOAD: Loaded value 5" in output
    assert_result(output, 8)


def test_memory_layout_and_multibyte_values() -> None:
    program = [
        "space:",
        "    first = 00000001",
        "    second = 0000001000000011",
        "    reserve: 2",
        "main:",
        "MOV R0, first",
        "MOV R1, second",
        "MOV R2, reserve",
        "MOV R3, [first]",
        "MOV R4, [second]",
        "MOV R5, [reserve]",
    ]

    output, symbols = run_simulation(program)


    assert symbols["second"] == symbols["first"] + 1
    assert symbols["reserve"] == symbols["second"] + 2
    assert output.count("MEM_LOAD: Reading from address") == 3
    assert "MEM_LOAD: Loaded value 1" in output
    assert "MEM_LOAD: Loaded value 2" in output
    assert "MEM_LOAD: Loaded value 0" in output


def test_memory_store_save() -> None:
    program = [
        "space:",
        "    target = 00000000",
        "main:",
        "MOV R0, V42",
        "SAVE R0, [target]",
        "MOV R1, [target]",
        "MOV R2, R1",
    ]

    output, _ = run_simulation(program)

    assert "MEM_STORE: Stored value 42" in output
    assert "MEM_LOAD: Loaded value 42" in output
    assert_result(output, 42)


def test_memory_store_overwrites_value() -> None:
    program = [
        "space:",
        "    target = 11111111",
        "main:",
        "MOV R0, V7",
        "SAVE R0, [target]",
        "MOV R1, [target]",
        "MOV R2, R1",
    ]

    output, _ = run_simulation(program)

    assert "MEM_STORE: Stored value 7" in output
    assert "MEM_LOAD: Loaded value 7" in output
    assert_result(output, 7)


def test_memory_store_multiple_targets() -> None:
    program = [
        "space:",
        "    first = 00000000",
        "    second = 00000000",
        "main:",
        "MOV R0, V10",
        "MOV R1, V20",
        "SAVE R0, [first]",
        "SAVE R1, [second]",
        "MOV R2, [first]",
        "MOV R3, [second]",
        "MOV R4, R2",
        "MOV R5, R3",
    ]

    output, _ = run_simulation(program)

    assert "MEM_STORE: Stored value 10" in output
    assert "MEM_STORE: Stored value 20" in output
    assert "MEM_LOAD: Loaded value 10" in output
    assert "MEM_LOAD: Loaded value 20" in output
    assert_result(output, 10)
    assert_result(output, 20)


def test_memory_store_truncates_to_byte() -> None:
    program = [
        "space:",
        "    target: 8",
        "main:",
        "MOV R0, V300",
        "SAVE R0, [target]",
        "MOV R1, [target]",
        "MOV R2, R1",
    ]

    output, _ = run_simulation(program)

    assert "MEM_STORE: Stored value 44" in output
    assert "MEM_LOAD: Loaded value 44" in output
    assert_result(output, 44)


def test_memory_storem_and_loadm_roundtrip() -> None:
    program = [
        "space:",
        "    target: 4",
        "main:",
        "MOV R0, V837",
        "SAVEM R0, [target]",
        "MOV R1, [target]",
        "MOVM R2, [target]",
        "MOV R3, R1",
        "MOV R4, R2",
    ]

    output, _ = run_simulation(program)

    assert "MEM_STORE_MULTI: Stored value 837" in output
    assert "MEM_LOAD: Loaded value 69" in output
    assert "MEM_LOAD_MULTI: Loaded value 837" in output
    assert_result(output, 69)
    assert_result(output, 837)


def test_memory_loadm_from_multibyte_literal() -> None:
    transfer_bytes = (RAM_ADDR_WIDTH + 7) // 8
    raw_bytes = [((index * 17) + 3) & 0xFF for index in range(transfer_bytes)]
    bit_literal = "".join(f"{value:08b}" for value in raw_bytes)
    expected = 0
    for index, value in enumerate(raw_bytes):
        expected |= value << (8 * index)
    expected &= MAX_ADDR_VALUE

    program = [
        "space:",
        f"    blob = {bit_literal}",
        "main:",
        "MOV R1, [blob]",
        "MOVM R0, [blob]",
        "MOV R2, R1",
        "MOV R3, R0",
    ]

    output, _ = run_simulation(program)

    assert f"MEM_LOAD: Loaded value {raw_bytes[0]}" in output
    assert f"MEM_LOAD_MULTI: Loaded value {expected}" in output
    assert_result(output, raw_bytes[0])
    assert_result(output, expected)


def test_memory_loadm_writes_requested_destination_register() -> None:
    program = [
        "space:",
        "    blob: 4",
        "main:",
        "MOV R1, V932",
        "SAVEM R1, [blob]",
        "MOVM R2, [blob]",
        "MOV R3, R2",
    ]

    output, _ = run_simulation(program)

    assert "MEM_LOAD_MULTI: Loaded value 932" in output
    assert "into R2" in output
    assert_result(output, 932)


def test_data_section_auto_aligns_code_start_to_word_boundary() -> None:
    program = [
        "space:",
        "    one = 00000001",
        "main:",
        "MOV R0, V42",
    ]

    output, _ = run_simulation(program)

    assert "BRANCH: Jumping to address 8" in output
    assert_result(output, 42)
