from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import pytest
from conftest import ROOT

from src.cpu.simulation.rtl_config import LOADER_MAX_PROGRAM_SIZE
from src.cpu.simulation.runner import _run_command


def _render_loader_tb(timeout_cycles: int) -> str:
    return rf"""`timescale 1ns/1ps
module LoaderTB;
    logic clock = 1'b0;
    logic reset = 1'b1;
    logic write_ram;
    logic [7:0] data_in_ram;
    logic [15:0] write_addr_ram;
    logic loader_done;
    integer cycles = 0;
    integer write_count = 0;

    Loader #(.ADDR_WIDTH(16)) dut (.*);
    always #5 clock = ~clock;

    initial begin
        #12 reset = 1'b0;
        forever begin
            @(negedge clock);
            cycles = cycles + 1;
            if (write_ram) begin
                $display("WRITE %0d %02x %0d", write_addr_ram, data_in_ram, cycles);
                write_count = write_count + 1;
            end
            if (loader_done) begin
                $display("DONE %0d %0d", write_count, cycles);
                $finish;
            end
            if (cycles > {timeout_cycles}) $fatal(1, "Loader timeout");
        end
    end
endmodule
"""


@pytest.mark.parametrize("quartus_paths", [False, True], ids=["icarus", "quartus-paths"])
def test_real_loader_writes_canonical_image_once_per_cycle(quartus_paths: bool) -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")

    image = bytes(
        int(line, 16)
        for line in (ROOT / "file.hex").read_text(encoding="ascii").splitlines()
        if line.strip()
    )
    size_header = (ROOT / "program_size.svh").read_text(encoding="ascii")
    declared = re.search(r"PROGRAM_IMAGE_SIZE\s*=\s*(\d+)", size_header)
    assert declared is not None, "program_size.svh does not declare PROGRAM_IMAGE_SIZE"
    assert int(declared[1]) == len(image)
    expected = image + bytes(4)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        package = tmp / "cpu_pkg.sv"
        package.write_text(
            "package cpu_pkg; localparam int USE_INIT_FILE = 0; "
            f"localparam int LOADER_MAX_PROGRAM_SIZE = {LOADER_MAX_PROGRAM_SIZE}; "
            "endpackage\n",
            encoding="ascii",
        )
        testbench = tmp / "loader_tb.sv"
        testbench.write_text(
            _render_loader_tb(len(expected) + 8), encoding="ascii"
        )
        executable = tmp / "loader_tb"
        cwd = ROOT / "quartus" if quartus_paths else ROOT
        define = [] if quartus_paths else ["-DSIMULATION"]
        _run_command(
            [
                "iverilog", "-g2012", *define, "-I", str(ROOT),
                "-s", "LoaderTB", "-o", str(executable),
                str(package), str(ROOT / "hdl" / "loader.sv"), str(testbench),
            ],
            cwd,
        )
        result = _run_command(["vvp", str(executable)], cwd)

    writes = [
        (int(address), int(value, 16), int(cycle))
        for address, value, cycle in re.findall(
            r"^WRITE (\d+) ([0-9a-fA-F]{2}) (\d+)$", result.stdout, re.MULTILINE
        )
    ]
    assert [(address, value) for address, value, _ in writes] == list(enumerate(expected))
    assert [cycle for _, _, cycle in writes] == list(range(2, len(expected) + 2))
    assert re.search(rf"^DONE {len(expected)} {len(expected) + 2}$", result.stdout, re.MULTILINE)
