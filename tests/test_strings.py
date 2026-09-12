from conftest import assert_result, run_simulation


def test_string_literal_mov_compare_and_alu() -> None:
    program = [
        "main:",
        'MOV R1, "a"',
        'CMP R1, "a"',
        "ADDEQ R2, R1, V1",
        'SUB R3, R2, "a"',
    ]

    output, _ = run_simulation(program)

    assert "Comparison:" in output
    assert_result(output, ord("a"))
    assert_result(output, ord("b"))
    assert_result(output, 1)


def test_string_literal_store_and_load_round_trip() -> None:
    program = [
        "space:",
        "    slot = 00000000",
        "main:",
        'MOV R0, "Z"',
        "SAVE R0, [slot]",
        "MOV R1, [slot]",
        'CMP R1, "Z"',
        'SUBEQ R2, R1, "A"',
    ]

    output, symbols = run_simulation(program)

    assert f"MEM_LOAD: Reading from address {symbols['slot']}" in output
    assert "MEM_STORE: Stored value 90" in output
    assert "MEM_LOAD: Loaded value 90" in output
    assert "Comparison:" in output
    assert_result(output, 25)


def test_space_string_initialization_and_layout() -> None:
    program = [
        "space:",
        '    first = "Hi"',
        '    second = "!"',
        "main:",
        "MOV R0, first",
        "MOV R1, second",
        "MOV R2, [first]",
        "MOV R3, [second]",
        "ADD R4, R2, V1",
    ]

    output, symbols = run_simulation(program)

    assert symbols["second"] == symbols["first"] + 2
    assert_result(output, symbols["first"])
    assert_result(output, symbols["second"])
    assert f"MEM_LOAD: Reading from address {symbols['first']} into R2" in output
    assert f"MEM_LOAD: Reading from address {symbols['second']} into R3" in output
    assert "MEM_LOAD: Loaded value 72" in output
    assert "MEM_LOAD: Loaded value 33" in output
    assert_result(output, 73)
