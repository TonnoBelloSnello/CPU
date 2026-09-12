from __future__ import annotations

import re
import shutil

import pytest

from src.cpu.simulation.runner import (
    DEFAULT_ADDR_WIDTH,
    _assemble_program,
    _compiled_icarus_workspace,
    _run_command,
)
from src.cpu.simulation.templates import render_loader_sv

pytestmark = pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not available on PATH",
)


_TESTBENCH = r"""
module WebFastEquivalenceTB;
    reg clock = 1'b0;
    reg [3:0] KEY = 4'hF;
    wire [9:0] LEDR;
    wire [6:0] HEX0, HEX1, HEX2, HEX3, HEX4, HEX5;
    wire [7:0] VGA_R, VGA_G, VGA_B;
    wire VGA_HS, VGA_VS, VGA_BLANK_N, VGA_SYNC_N, VGA_CLK;
    integer cycles = 0;

    CPU #(
        .ADDR_WIDTH(16),
        .USE_SLOW_CLOCK(0),
        .CLOCK_FREQ_HZ(1)
    ) dut (
        .clock(clock), .KEY(KEY), .LEDR(LEDR),
        .HEX0(HEX0), .HEX1(HEX1), .HEX2(HEX2),
        .HEX3(HEX3), .HEX4(HEX4), .HEX5(HEX5),
        .VGA_R(VGA_R), .VGA_G(VGA_G), .VGA_B(VGA_B),
        .VGA_HS(VGA_HS), .VGA_VS(VGA_VS),
        .VGA_BLANK_N(VGA_BLANK_N), .VGA_SYNC_N(VGA_SYNC_N),
        .VGA_CLK(VGA_CLK)
    );

    always #0.1 clock = ~clock;

    initial begin
        while (!dut.halted && cycles < 2000) begin
            @(posedge clock);
            cycles = cycles + 1;
        end
        if (!dut.halted)
            $fatal(1, "CPU did not halt");
        @(negedge clock);
        $display("EQUIV cycles=%0d r0=%h r1=%h r2=%h r3=%h r4=%h r6=%h r7=%h r8=%h cpsr=%h fb=%h",
                 cycles,
                 dut.data_out_registers[0], dut.data_out_registers[1],
                 dut.data_out_registers[2], dut.data_out_registers[3],
                 dut.data_out_registers[4], dut.data_out_registers[6],
                 dut.data_out_registers[7], dut.data_out_registers[8],
                 dut.data_out_cpsr, dut.fb_inst.fb_mem[964]);
        $finish;
    end
endmodule
"""


def _simulate(*, fast: bool) -> str:
    program, _ = _assemble_program(
        [
            "main:",
            "FMOV R0, F3.0",
            "FMOV R1, F2.0",
            "FADD R2, R0, R1",
            "FDIV R3, R0, R1",
            "FSUB R6, R0, R1",
            "FMUL R8, R0, R1",
            "MOV R4, V4",
            "MOV R5, V6",
            "PIXELNB R4, R5, V10",
            "PIXEL R4, R5, V20",
            "FCMP R0, R1",
            "MOVGT R7, V99",
        ]
    )
    defines = ("SIMULATION", "SNAPSHOT_MODE")
    if fast:
        defines += ("WEB_FAST_SIMULATION",)

    with _compiled_icarus_workspace(
        program,
        executable_name="web_fast_equivalence.vvp",
        defines=defines,
        top_module="WebFastEquivalenceTB",
        testbench_name="web_fast_equivalence_tb.sv",
        testbench_text=_TESTBENCH,
        loader_text=render_loader_sv(program, addr_width=DEFAULT_ADDR_WIDTH),
    ) as (workspace, executable):
        result = _run_command(["vvp", str(executable)], workspace)
    return (result.stdout or "") + (result.stderr or "")


def test_web_fast_mode_is_cycle_and_state_equivalent_and_keeps_pixel_events() -> None:
    regular = _simulate(fast=False)
    fast = _simulate(fast=True)

    marker = re.compile(r"^EQUIV .+$", re.MULTILINE)
    regular_state = marker.search(regular)
    fast_state = marker.search(fast)
    assert regular_state is not None
    assert fast_state is not None
    assert fast_state.group(0) == regular_state.group(0)
    assert "r2=4500" in fast_state.group(0)
    assert "r3=3e00" in fast_state.group(0)
    assert "r6=3c00" in fast_state.group(0)
    assert "r7=0063" in fast_state.group(0)
    assert "r8=4600" in fast_state.group(0)
    assert "fb=14" in fast_state.group(0)

    pixel_events = re.compile(r"^PIXEL:.*$", re.MULTILINE)
    assert pixel_events.findall(fast) == pixel_events.findall(regular)
    assert len(pixel_events.findall(fast)) == 2
    assert "Storing result" in regular
    assert "Storing result" not in fast
