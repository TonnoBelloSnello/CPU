from conftest import assert_result, run_simulation

PC_DEST = "in PC"


def test_mov_pc_immediate_jumps_to_label() -> None:
    program = [
        "main:",
        "MOV R0, V1",
        "MOV PC, jumped",
        "MOV R1, V99",
        "jumped:",
        "MOV R2, V42",
    ]

    output, labels = run_simulation(program)

    assert_result(output, labels["jumped"], dest=PC_DEST)
    assert_result(output, 42)
    assert_result(output, 99, found=False)


def test_mov_pc_register_jumps_to_label() -> None:
    program = [
        "main:",
        "MOV R0, target",
        "MOV PC, R0",
        "MOV R1, V77",
        "target:",
        "MOV R2, V13",
    ]

    output, labels = run_simulation(program)

    assert_result(output, labels["target"], dest=PC_DEST)
    assert_result(output, 13)
    assert_result(output, 77, found=False)


def test_moveq_pc_skipped_when_condition_false() -> None:
    program = [
        "main:",
        "MOV R0, V5",
        "CMP R0, V6",
        "MOVEQ PC, skipped_to",
        "MOV R1, V33",
        "B done",
        "skipped_to:",
        "MOV R1, V99",
        "done:",
    ]

    output, labels = run_simulation(program)

    assert "Condition not met" in output
    assert_result(output, 33)
    assert f"BRANCH: Jumping to address {labels['done']}" in output
    assert_result(output, 99, found=False)


def test_mem_load_into_pc_jumps_to_loaded_address() -> None:
    program = [
        "space:",
        "    jump_slot = 00000000",
        "main:",
        "MOV R0, destination",
        "SAVE R0, [jump_slot]",
        "MOV PC, [jump_slot]",
        "MOV R1, V88",
        "destination:",
        "MOV R2, V21",
    ]

    output, labels = run_simulation(program)

    assert f"MEM_LOAD: Loaded value {labels['destination'] & 0xFF}" in output
    assert "into PC" in output
    assert_result(output, 21)
    assert_result(output, 88, found=False)


def test_pop_pc_returns_to_pushed_address() -> None:
    program = [
        "main:",
        "MOV R13, V256",
        "MOV R0, resumed",
        "PUSH R0",
        "POP PC",
        "MOV R1, V55",
        "resumed:",
        "MOV R2, V34",
    ]

    output, labels = run_simulation(program)

    assert f"STACK_POP: Loaded value {labels['resumed']}" in output
    assert "into PC" in output
    assert_result(output, 34)
    assert_result(output, 55, found=False)
