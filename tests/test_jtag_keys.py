from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest
from conftest import ROOT, assert_result
from test_waitk import run_waitk_simulation

from scripts.board.jtag_keys import (
    PRESETS,
    TEXT_BACKSPACE,
    TEXT_CLEAR,
    TEXT_GO,
    TEXT_LEFT,
    TEXT_RIGHT,
    TEXT_ROW,
    TEXT_SELECT,
    TEXT_SPACE,
    KeymapError,
    SessionError,
    _find_quartus_stp,
    main,
    parse_cursor,
    parse_keymap,
    resolve_binding,
    text_key_sequence,
    text_target,
)
from src.cpu.simulation.runner import _run_command

MMIO_KEYS_TB = r"""`timescale 1ns/1ps
module MmioKeysTB;
    import cpu_pkg::*;

    localparam int AW = cpu_pkg::RAM_ADDR_WIDTH;

    logic          clock = 1'b0;
    logic          reset = 1'b1;
    logic [AW-1:0] read_addr = '0;
    logic [AW-1:0] write_addr = '0;
    logic [7:0]    write_data = '0;
    logic          write_en = 1'b0;
    wire           write_hit;
    wire           read_sel;
    wire [7:0]     read_data;
    logic [3:0]    key_n = 4'hF;
    logic [3:0]    key_jtag = 4'h0;
    logic [AW-1:0] led_value = '0;
    logic [AW-1:0] hex_value = '0;
    wire           led_write;
    wire           hex_write;
    wire [7:0]     display_write_byte;
    wire [1:0]     display_write_index;

    MMIO #(.DATA_WIDTH(8), .ADDR_WIDTH(AW)) dut (.*);

    always #5 clock = ~clock;

    // Reads register the address and present data on the next cycle, so the
    // stimulus settles before a posedge and the result is read after it.
    task automatic sample(input logic [3:0] keys_low, input logic [3:0] jtag);
        begin
            key_n = ~keys_low;
            key_jtag = jtag;
            read_addr = MMIO_BASE + MMIO_OFF_KEYS;
            @(posedge clock);
            @(negedge clock);
            $display("KEYS %01x %01x %01x %0d",
                     keys_low, jtag, read_data[3:0], read_sel);
        end
    endtask

    initial begin
        @(negedge clock);
        reset = 1'b0;
        sample(4'h0, 4'h0);   // idle board, idle session
        sample(4'h1, 4'h0);   // physical KEY0 alone
        sample(4'h0, 4'h1);   // host KEY0 alone -- indistinguishable
        sample(4'h0, 4'h8);   // host KEY3
        sample(4'h1, 4'h2);   // one from each side
        sample(4'h1, 4'h1);   // same bit from both sides
        sample(4'h0, 4'hF);   // every key from the host
        sample(4'hF, 4'h0);   // every key from the board
        $finish;
    end
endmodule
"""


def _run_mmio_keys_testbench() -> list[tuple[int, int, int, int]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        testbench = tmp / "mmio_keys_tb.sv"
        testbench.write_text(MMIO_KEYS_TB, encoding="ascii")
        executable = tmp / "mmio_keys_tb"
        _run_command(
            [
                "iverilog", "-g2012", "-DSIMULATION",
                "-s", "MmioKeysTB", "-o", str(executable),
                str(ROOT / "hdl" / "cpu_pkg.sv"),
                str(ROOT / "hdl" / "mmio.sv"),
                str(testbench),
            ],
            ROOT,
        )
        result = _run_command(["vvp", str(executable)], ROOT)

    return [
        (int(keys, 16), int(jtag, 16), int(seen, 16), int(sel))
        for keys, jtag, seen, sel in re.findall(
            r"^KEYS ([0-9a-f]) ([0-9a-f]) ([0-9a-f]) (\d)$",
            result.stdout,
            re.MULTILINE,
        )
    ]


@pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not available on PATH",
)
def test_keys_slot_is_the_union_of_board_and_host_presses() -> None:
    samples = _run_mmio_keys_testbench()

    assert len(samples) == 8, f"testbench emitted {len(samples)} samples"
    for keys, jtag, seen, sel in samples:
        assert seen == keys | jtag, (
            f"KEY={keys:#x} JTAG={jtag:#x} read back {seen:#x}"
        )
        assert sel == 1, "the window must claim the read regardless of the mask"


@pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not available on PATH",
)
def test_host_source_alone_is_enough_to_report_a_press() -> None:
    samples = {(keys, jtag): seen for keys, jtag, seen, _ in _run_mmio_keys_testbench()}

    assert samples[(0x0, 0x0)] == 0x0
    assert samples[(0x0, 0x1)] == 0x1
    assert samples[(0x0, 0xF)] == 0xF
    assert samples[(0x1, 0x1)] == 0x1


def test_waitk_unblocks_on_a_host_key_with_the_board_idle() -> None:
    program = [
        "main:",
        "WAITK R1, V2",
        "MOV R2, V7",
    ]

    output = run_waitk_simulation(program, key_events=[], jtag_events=[(30, 0b0010)])

    assert_result(output, 2)
    assert_result(output, 7)
    assert "Halt: Encountered null instruction" in output


def test_waitk_ignores_a_host_key_outside_its_mask() -> None:
    program = [
        "main:",
        "WAITK R1, V2",
        "MOV R2, V7",
    ]

    output = run_waitk_simulation(
        program, key_events=[], jtag_events=[(30, 0b0001)], max_cycles=400
    )

    assert "Simulation timeout" in output, "WAITK woke on an unselected key"


def test_missing_quartus_stp_is_reported_not_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.board.jtag_keys.shutil.which", lambda _name: None)
    monkeypatch.delenv("QUARTUS_ROOTDIR", raising=False)

    with pytest.raises(SessionError, match="quartus_stp"):
        _find_quartus_stp(None)


def test_explicit_quartus_stp_path_must_exist(tmp_path: Path) -> None:
    with pytest.raises(SessionError, match="not found"):
        _find_quartus_stp(str(tmp_path / "nope.exe"))


@pytest.fixture
def no_hardware(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("arguments must be rejected before any JTAG access")

    monkeypatch.setattr("scripts.board.jtag_keys.run", refuse)
    monkeypatch.setattr("scripts.board.jtag_keys._find_quartus_stp", refuse)


@pytest.mark.parametrize(
    "keymap",
    ["", "12345", "112", "a=", "a=9", "a=0,a=1", "ab=0", "a=x", "=0"],
)
@pytest.mark.usefixtures("no_hardware")
def test_malformed_keymaps_are_rejected(keymap: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--map", keymap])

    assert excinfo.value.code == 2


def test_the_positional_form_accepts_any_characters() -> None:
    assert parse_keymap("a0") == {"a": 0b01, "0": 0b10}


def test_caps_lock_does_not_silently_disable_every_binding() -> None:
    bindings = parse_keymap(PRESETS["doom"])

    assert resolve_binding("W", bindings) == bindings["w"]
    assert resolve_binding("F", bindings) == bindings["f"]


def test_an_explicit_upper_case_binding_beats_the_folded_one() -> None:
    bindings = parse_keymap("a=0,A=3")

    assert resolve_binding("A", bindings) == 0b1000
    assert resolve_binding("a", bindings) == 0b0001


@pytest.mark.skipif(os.name != "nt", reason="live key state is a Windows API")
def test_every_bound_character_maps_to_a_virtual_key() -> None:
    from scripts.board.jtag_keys import KeyStatePoller

    poller = KeyStatePoller("".join(parse_keymap(PRESETS["doom"])))

    assert poller.usable
    assert poller.held() <= set(parse_keymap(PRESETS["doom"]))


def test_an_unbound_key_drives_nothing() -> None:
    assert resolve_binding("z", parse_keymap("1234")) is None


def test_a_trailing_comma_is_tolerated() -> None:
    assert parse_keymap("a=0,") == parse_keymap("a=0")


def test_positional_map_assigns_one_key_per_character_low_bit_first() -> None:
    assert parse_keymap("1234") == {"1": 0b0001, "2": 0b0010, "3": 0b0100, "4": 0b1000}


def test_a_binding_can_cover_several_keys_at_once() -> None:
    bindings = parse_keymap("w=1,f=12")

    assert bindings["w"] == 0b0010
    assert bindings["f"] == 0b0110


def test_named_characters_reach_keys_a_spec_cannot_spell() -> None:
    assert parse_keymap("space=12") == {" ": 0b0110}
    assert parse_keymap("comma=0") == {",": 0b0001}


def test_doom_preset_matches_the_program_control_scheme() -> None:
    bindings = parse_keymap(PRESETS["doom"])

    assert bindings["a"] == 0b0001
    assert bindings["w"] == 0b0010
    assert bindings["s"] == 0b0100
    assert bindings["d"] == 0b1000
    assert bindings["f"] == 0b0110
    assert bindings[" "] == 0b0110
    assert bindings["f"] | bindings["d"] == 0b1110


@pytest.mark.usefixtures("no_hardware")
def test_map_and_preset_together_are_refused_rather_than_ranked() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--map", "1234", "--preset", "doom"])

    assert excinfo.value.code == 2


def test_parse_keymap_reports_the_offending_entry() -> None:
    with pytest.raises(KeymapError, match="key index"):
        parse_keymap("a=0,w=5")


def test_typed_characters_reach_the_grid_keys_that_carry_them() -> None:
    assert text_target("a") == 0
    assert text_target("A") == 0
    assert text_target("z") == 25
    assert text_target(".") == 26
    assert text_target(",") == 27
    assert text_target(" ") == TEXT_SPACE
    assert text_target("\r") == TEXT_GO
    assert text_target("\n") == TEXT_GO
    assert text_target("\x08") == TEXT_BACKSPACE
    assert text_target("\x7f") == TEXT_BACKSPACE
    assert text_target("\x15") == TEXT_CLEAR
    assert text_target("1") is None
    assert text_target("?") is None


def test_the_walk_takes_the_short_way_round_and_only_advances_rows() -> None:
    assert text_key_sequence(1, 0) == [TEXT_RIGHT, TEXT_SELECT]
    assert text_key_sequence(0, 1) == [TEXT_LEFT, TEXT_SELECT]
    assert text_key_sequence(7, 0) == [TEXT_LEFT, TEXT_SELECT]
    assert text_key_sequence(4, 0) == [TEXT_RIGHT] * 4 + [TEXT_SELECT]
    assert text_key_sequence(0, 8) == [TEXT_ROW] * 3 + [TEXT_SELECT]
    assert text_key_sequence(8, 0) == [TEXT_ROW, TEXT_SELECT]
    assert text_key_sequence(0, 0) == [TEXT_SELECT]
    assert max(len(text_key_sequence(t, s)) for t in range(32) for s in range(32)) == 8


def test_cursor_spec_accepts_grid_characters_and_the_special_labels() -> None:
    assert parse_cursor("A") == 0
    assert parse_cursor("z") == 25
    assert parse_cursor(" ") == TEXT_SPACE
    assert parse_cursor("go") == TEXT_GO
    assert parse_cursor("GO") == TEXT_GO
    assert parse_cursor("cl") == TEXT_CLEAR
    assert parse_cursor("bs") == TEXT_BACKSPACE
    for bad in ("1", "??", ""):
        with pytest.raises(KeymapError, match="not a key on the grid"):
            parse_cursor(bad)


@pytest.mark.usefixtures("no_hardware")
@pytest.mark.parametrize(
    "argv",
    [
        ["--type", "--map", "1234"],
        ["--type", "--preset", "doom"],
        ["--type", "--toggle"],
        ["--type", "--pulse"],
        ["--cursor", "B"],
    ],
)
def test_type_mode_refuses_the_options_it_would_silently_ignore(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(argv)

    assert excinfo.value.code == 2


def test_the_walk_types_into_the_actual_program() -> None:
    from scripts.ml.simulate import await_input, press_key
    from scripts.ml.tiny_text import PROGRAM, compile_program, load_model
    from src.cpu.encoder.assemble import assemble
    from src.cpu.simulation.emulator import CPUEmulator

    program = assemble(compile_program(load_model()).splitlines(), PROGRAM.parent)
    cpu = CPUEmulator(program.to_bytes())
    await_input(cpu)
    assert cpu.memory[program.symbols["selected"]] == 0, "--cursor defaults to where it starts"

    cursor = 0
    for char in "CIAO, W.":
        target = text_target(char)
        assert target is not None
        for mask in text_key_sequence(target, cursor):
            press_key(cpu, program.symbols, mask)
        cursor = target
        assert cpu.memory[program.symbols["selected"]] == target, char

    base = program.symbols["prompt"]
    typed = bytes(cpu.memory[base : base + 25]).split(b"\0")[0].decode("ascii")
    assert typed == "CIAO, W."
