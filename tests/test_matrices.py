from conftest import assert_result, run_simulation


def test_inline_matrix_literal_mov_and_register_indirect_access() -> None:
    matrix_key = "{{1,0},{2,5},{3,0}}"
    program = [
        "space:",
        "    slot = 00000000",
        "main:",
        "MOV R1, {{1, 0}, {2, 5}, {3, 0}}",
        "MOV R2, [R1]",
        "ADD R1, R1, V3",
        "MOV R3, [R1]",
        "ADD R4, R2, R3",
        "SAVE R4, [slot]",
        "MOV R5, [slot]",
    ]

    output, symbols = run_simulation(program)

    assert matrix_key in symbols
    assert f"MEM_LOAD: Reading from address {symbols[matrix_key]} into R2" in output
    assert "MEM_LOAD: Loaded value 1" in output
    assert "MEM_LOAD: Loaded value 5" in output
    assert "MEM_STORE: Stored value 6" in output
    assert_result(output, 6)


def test_space_matrix_initialization_compare_and_arithmetic() -> None:
    program = [
        "space:",
        "    m = {{1, 2}, {3, 4}}",
        "main:",
        "MOV R0, [m]",
        "MOV R1, m",
        "ADD R1, R1, V1",
        "MOV R2, [R1]",
        "CMP R2, R0",
        "SUB R3, R2, R0",
        "ADDEQ R4, R3, V10",
    ]

    output, symbols = run_simulation(program)

    assert symbols["m"] >= 4
    assert "Comparison:" in output
    assert_result(output, 1)


def test_elementwise_matrix_addition_via_register_indirect_loop() -> None:
    program = [
        "space:",
        "    out: 6",
        "main:",
        "MOV R1, {{1, 0}, {2, 5}, {3, 0}}",
        "MOV R2, {{2, 1}, {1, 0}, {4, 2}}",
        "MOV R3, out",
        "MOV R4, V6",
        "loop:",
        "MOV R5, [R1]",
        "MOV R6, [R2]",
        "ADD R7, R5, R6",
        "SAVE R7, [R3]",
        "ADD R1, R1, V1",
        "ADD R2, R2, V1",
        "ADD R3, R3, V1",
        "SUB R4, R4, V1",
        "CMP R4, V0",
        "BNE loop",
        "MOV R8, out",
        "MOV R9, [R8]",
        "ADD R8, R8, V3",
        "MOV R10, [R8]",
        "ADD R11, R9, R10",
    ]

    output, symbols = run_simulation(program)

    assert "MEM_STORE: Stored value 3" in output
    assert "MEM_STORE: Stored value 5" in output
    assert f"MEM_LOAD: Reading from address {symbols['out']} into R9" in output
    assert_result(output, 8)


def test_direct_matrix_mul_named_matrices() -> None:
    result_key = "mmul:{{1,2,3},{4,5,6}}:{{7,8},{9,10},{11,12}}"
    program = [
        "space:",
        "    A = {{1, 2, 3}, {4, 5, 6}}",
        "    B = {{7, 8}, {9, 10}, {11, 12}}",
        "main:",
        "MUL R0, A, B",
        "MOV R1, [R0]",
        "ADD R0, R0, V1",
        "MOV R2, [R0]",
        "ADD R3, R1, R2",
        "ADD R0, V1",
        "MOV R2, [R0]",
        "CMP R2, V64",
    ]

    output, symbols = run_simulation(program)

    assert result_key in symbols
    assert_result(output, symbols[result_key])
    assert "MEM_LOAD: Loaded value 58" in output
    assert "MEM_LOAD: Loaded value 64" in output
    assert "MEM_LOAD: Loaded value 139" in output
    assert_result(output, 122)
    assert "Comparison:" in output


def test_direct_matrix_mul_inline_literals() -> None:
    result_key = "mmul:{{1,2},{3,4}}:{{5},{6}}"
    program = [
        "main:",
        "MUL R5, {{1, 2}, {3, 4}}, {{5}, {6}}",
        "MOV R6, [R5]",
        "ADD R5, R5, V1",
        "MOV R7, [R5]",
        "ADD R8, R6, R7",
    ]

    output, symbols = run_simulation(program)

    assert result_key in symbols
    assert_result(output, symbols[result_key])
    assert "MEM_LOAD: Loaded value 17" in output
    assert "MEM_LOAD: Loaded value 39" in output
    assert_result(output, 56)
