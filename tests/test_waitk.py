from __future__ import annotations

import shutil

import pytest
from conftest import _assemble_program, _render_loader_sv, assert_result

from src.cpu.encoder.steps.encoder import encode_asm
from src.cpu.simulation.runner import _compiled_icarus_workspace, _run_command


def _render_waitk_tb(
    key_events: list[tuple[int, int]],
    max_cycles: int,
    jtag_events: list[tuple[int, int]] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("`timescale 1ns/1ps")
    lines.append("")
    lines.append("module WaitKeyTB;")
    lines.append("    reg clock = 1'b0;")
    lines.append("    reg [3:0] KEY = 4'hF;")
    lines.append("    wire [9:0] LEDR;")
    lines.append("    wire [6:0] HEX0, HEX1, HEX2, HEX3, HEX4, HEX5;")
    lines.append("    wire [7:0] VGA_R, VGA_G, VGA_B;")
    lines.append("    wire VGA_HS, VGA_VS, VGA_BLANK_N, VGA_SYNC_N, VGA_CLK;")
    lines.append(f"    localparam int MAX_CYCLES = {max_cycles};")
    lines.append("    localparam real clock_period = 0.2;")
    lines.append("")
    lines.append("    CPU #(")
    lines.append("        .USE_SLOW_CLOCK(0),")
    lines.append("        .CLOCK_FREQ_HZ(1)")
    lines.append("    ) dut (")
    lines.append("        .clock(clock),")
    lines.append("        .KEY(KEY),")
    lines.append("        .LEDR(LEDR),")
    lines.append("        .HEX0(HEX0),")
    lines.append("        .HEX1(HEX1),")
    lines.append("        .HEX2(HEX2),")
    lines.append("        .HEX3(HEX3),")
    lines.append("        .HEX4(HEX4),")
    lines.append("        .HEX5(HEX5),")
    lines.append("        .VGA_R(VGA_R),")
    lines.append("        .VGA_G(VGA_G),")
    lines.append("        .VGA_B(VGA_B),")
    lines.append("        .VGA_HS(VGA_HS),")
    lines.append("        .VGA_VS(VGA_VS),")
    lines.append("        .VGA_BLANK_N(VGA_BLANK_N),")
    lines.append("        .VGA_SYNC_N(VGA_SYNC_N),")
    lines.append("        .VGA_CLK(VGA_CLK)")
    lines.append("    );")
    lines.append("")
    lines.append("    initial begin")
    lines.append("        clock = 1'b0;")
    lines.append("        forever #(clock_period/2) clock = ~clock;")
    lines.append("    end")
    lines.append("")
    lines.append("    integer cycles;")
    lines.append("    initial begin")
    lines.append("        cycles = 0;")
    lines.append("        while (!dut.halted && cycles < MAX_CYCLES) begin")
    lines.append("            @(posedge clock);")
    lines.append("            cycles = cycles + 1;")
    if key_events:
        lines.append("            case (cycles)")
        for cycle, value in key_events:
            lines.append(f"                {cycle}: KEY <= 4'b{value:04b};")
        lines.append("                default: ;")
        lines.append("            endcase")
    if jtag_events:
        lines.append("            case (cycles)")
        for cycle, value in jtag_events:
            lines.append(f"                {cycle}: dut.jtag_key_raw <= 4'b{value:04b};")
        lines.append("                default: ;")
        lines.append("            endcase")
    lines.append("        end")
    lines.append("        if (!dut.halted) begin")
    lines.append('            $display("ERROR: Simulation timeout - CPU did not halt");')
    lines.append("        end")
    lines.append("        $finish;")
    lines.append("    end")
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines) + "\n"


def run_waitk_simulation(
    program_lines: list[str],
    key_events: list[tuple[int, int]],
    *,
    max_cycles: int = 2000,
    jtag_events: list[tuple[int, int]] | None = None,
) -> str:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")

    program_bytes, _ = _assemble_program(program_lines)

    with _compiled_icarus_workspace(
        program_bytes,
        executable_name="cpu_waitk",
        top_module="WaitKeyTB",
        testbench_name="waitk_tb.sv",
        testbench_text=_render_waitk_tb(key_events, max_cycles, jtag_events),
        loader_text=_render_loader_sv(program_bytes),
        command_runner=_run_command,
    ) as (tmp_path, output_path):
        run_result = _run_command(["vvp", str(output_path)], tmp_path)

    return run_result.stdout + run_result.stderr


def test_waitk_encoding_immediate_mask() -> None:
    word = encode_asm(["WAITK R2, V15"])[0]
    assert ((word >> 26) & 0b11) == 0b01
    assert ((word >> 25) & 0b1) == 0b1
    assert ((word >> 21) & 0xF) == 0xD
    assert ((word >> 12) & 0xF) == 0x2
    assert (word & 0xFFF) == 0x00F


def test_waitk_encoding_register_mask() -> None:
    word = encode_asm(["WAITK R2, R1"])[0]
    assert ((word >> 26) & 0b11) == 0b01
    assert ((word >> 25) & 0b1) == 0b0
    assert ((word >> 21) & 0xF) == 0xD
    assert ((word >> 12) & 0xF) == 0x2
    assert (word & 0xF) == 0x1


def test_waitk_rejects_memory_operand() -> None:
    with pytest.raises(ValueError, match="WAITK does not support memory operands"):
        encode_asm(["WAITK R1, [mask]"], {"mask": 0})


def test_waitk_waits_for_selected_key_and_writes_mask() -> None:
    program = [
        "main:",
        "WAITK R1, V2",
        "MOV R2, V7",
    ]
    output = run_waitk_simulation(program, key_events=[(30, 0b1101)])
    assert "WAITK: waiting for selected mask=0x2" in output
    assert_result(output, 2)
    assert_result(output, 7)
    assert "Halt: Encountered null instruction" in output


def test_waitk_writes_multi_key_bitmask() -> None:
    program = [
        "main:",
        "WAITK R1, V15",
        "MOV R2, V1",
    ]
    output = run_waitk_simulation(program, key_events=[(30, 0b0101)])
    assert_result(output, 10)
    assert_result(output, 1)


def test_waitk_zero_mask_treated_as_any_key_for_immediate_and_register() -> None:
    program_imm = [
        "main:",
        "WAITK R1, V0",
        "MOV R2, V3",
    ]
    output_imm = run_waitk_simulation(program_imm, key_events=[(30, 0b1110)])
    assert_result(output_imm, 1)
    assert_result(output_imm, 3)

    program_reg = [
        "main:",
        "MOV R3, V0",
        "WAITK R1, R3",
        "MOV R2, V6",
    ]
    output_reg = run_waitk_simulation(program_reg, key_events=[(30, 0b1011)])
    assert_result(output_reg, 4)
    assert_result(output_reg, 6)


def test_waitk_register_mask_and_condition_skip() -> None:
    program_reg_mask = [
        "main:",
        "MOV R3, V8",
        "WAITK R1, R3",
        "MOV R2, V5",
    ]
    output_reg_mask = run_waitk_simulation(program_reg_mask, key_events=[(30, 0b0111)])
    assert_result(output_reg_mask, 8)
    assert_result(output_reg_mask, 5)

    program_cond_skip = [
        "main:",
        "MOV R0, V0",
        "CMP R0, V0",
        "WAITKNE R1, V15",
        "MOV R2, V9",
    ]
    output_cond_skip = run_waitk_simulation(program_cond_skip, key_events=[])
    assert "Condition not met (cond=1), skipping instruction" in output_cond_skip
    assert_result(output_cond_skip, 9)


def test_waitknb_encoding_immediate_mask() -> None:
    word = encode_asm(["WAITKNB R2, V15"])[0]
    assert ((word >> 26) & 0b11) == 0b11
    assert ((word >> 25) & 0b1) == 0b1
    assert ((word >> 21) & 0xF) == 0x7
    assert ((word >> 12) & 0xF) == 0x2
    assert (word & 0xFFF) == 0x00F


def test_waitknb_encoding_register_mask() -> None:
    word = encode_asm(["WAITKNB R2, R1"])[0]
    assert ((word >> 26) & 0b11) == 0b11
    assert ((word >> 25) & 0b1) == 0b0
    assert ((word >> 21) & 0xF) == 0x7
    assert ((word >> 12) & 0xF) == 0x2
    assert (word & 0xF) == 0x1


def test_waitknb_rejects_memory_operand() -> None:
    with pytest.raises(ValueError, match="WAITKNB does not support memory operands"):
        encode_asm(["WAITKNB R1, [mask]"], {"mask": 0})


def test_waitknb_non_blocking_continues_without_key() -> None:
    program = [
        "main:",
        "WAITKNB R1, V15",
        "MOV R2, V7",
    ]
    output = run_waitk_simulation(program, key_events=[])
    assert "WAITKNB: hit mask=0x0 selected=0xf" in output
    assert_result(output, 0)
    assert_result(output, 7)
    assert "Halt: Encountered null instruction" in output


def test_waitknb_selected_key_and_zero_mask_behavior() -> None:
    program_selected = [
        "main:",
        "WAITKNB R1, V2",
        "MOV R2, V5",
    ]
    output_selected = run_waitk_simulation(program_selected, key_events=[(1, 0b1101)])
    assert "WAITKNB: hit mask=0x2 selected=0x2" in output_selected
    assert_result(output_selected, 2)
    assert_result(output_selected, 5)

    program_any = [
        "main:",
        "WAITKNB R1, V0",
        "MOV R2, V3",
    ]
    output_any = run_waitk_simulation(program_any, key_events=[(1, 0b1110)])
    assert "WAITKNB: hit mask=0x1 selected=0xf" in output_any
    assert_result(output_any, 1)
    assert_result(output_any, 3)


def test_waitknb_register_mask_and_condition_skip() -> None:
    program_reg_mask = [
        "main:",
        "MOV R3, V8",
        "WAITKNB R1, R3",
        "MOV R2, V5",
    ]
    output_reg_mask = run_waitk_simulation(program_reg_mask, key_events=[(1, 0b0111)])
    assert "WAITKNB: hit mask=0x8 selected=0x8" in output_reg_mask
    assert_result(output_reg_mask, 8)
    assert_result(output_reg_mask, 5)

    program_cond_skip = [
        "main:",
        "MOV R0, V0",
        "CMP R0, V0",
        "WAITKNBNE R1, V15",
        "MOV R2, V9",
    ]
    output_cond_skip = run_waitk_simulation(program_cond_skip, key_events=[])
    assert "Condition not met (cond=1), skipping instruction" in output_cond_skip
    assert_result(output_cond_skip, 9)
