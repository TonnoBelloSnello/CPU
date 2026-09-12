from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from conftest import ROOT

from src.cpu.encoder.utils.hex_to_mif import hex_to_mif
from src.cpu.simulation import runner as runner_module
from src.cpu.simulation.parser import parse_snapshot_output
from src.cpu.simulation.rtl_config import LOADER_MAX_PROGRAM_SIZE
from src.cpu.simulation.runner import (
    SimulationError,
    _assemble_program,
    run_snapshot,
    stream_snapshot_events,
)

ENCODER_OUT = ROOT / "src" / "cpu" / "encoder" / "out"

from src.cpu.simulation.templates import (
    MEMORY_END,
    MEMORY_START,
    REGISTER_END,
    REGISTER_START,
    render_loader_sv,
)


def _has_icarus() -> bool:
    return shutil.which("iverilog") is not None and shutil.which("vvp") is not None


def test_runner_bootstrap_targets_main_after_leading_helper() -> None:
    source = [
        "helper:",
        "    MOV R0, V9",
        "main:",
        "    MOV R1, V2",
    ]

    image, labels = _assemble_program(source)
    bootstrap = int.from_bytes(image[:4], byteorder="little")

    assert labels == {"helper": 4, "main": 8}
    assert bootstrap == 0xEC000008


def test_runner_keeps_main_in_branch_namespace() -> None:
    image, labels = _assemble_program(
        ["helper:", "MOV R0, V1", "main:", "B main"]
    )

    branch = int.from_bytes(image[-8:-4], byteorder="little")
    assert branch & 0xFFF == labels["main"] == 8


def _encode_with_cli(tmp_path: Path, stem: str, source: str) -> subprocess.CompletedProcess[str]:
    source_path = tmp_path / f"{stem}.de1"
    source_path.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "src.cpu.encoder.main", str(source_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_and_runner_offset_zero_length_data_after_bootstrap(tmp_path: Path) -> None:
    stem = f"zero_length_{uuid.uuid4().hex}"
    output_path = ENCODER_OUT / f"{stem}.bin"
    source = "space:\n    zero: 0\nmain:\n    MOV R0, zero\n"

    try:
        completed = _encode_with_cli(tmp_path, stem, source)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        cli_image = output_path.read_bytes()
    finally:
        output_path.unlink(missing_ok=True)

    runner_image, symbols = _assemble_program(source.splitlines())
    assert symbols["zero"] == 4
    assert cli_image == runner_image[:-4]
    assert int.from_bytes(cli_image[4:8], "little") & 0xFFF == 4


def test_cli_and_runner_reject_a_space_section_after_code(tmp_path: Path) -> None:
    stem = f"late_space_{uuid.uuid4().hex}"
    output_path = ENCODER_OUT / f"{stem}.bin"
    source = "main:\n    MOV R0, V0\nspace:\n    late: 1\n"

    try:
        completed = _encode_with_cli(tmp_path, stem, source)
        assert completed.returncode != 0
        assert "must precede executable code" in completed.stdout + completed.stderr
        assert not output_path.exists()
    finally:
        output_path.unlink(missing_ok=True)

    with pytest.raises(SimulationError, match="must precede executable code"):
        _assemble_program(source.splitlines())


@pytest.mark.parametrize(
    "label",
    ["__fp16_3C00", "bad-name", "9start", "R0", "SP", "LE", "HEX", "V5", "VB101", "F1"],
)
def test_runner_rejects_reserved_or_invalid_code_labels(label: str) -> None:
    with pytest.raises(SimulationError, match=r"[Cc]ode label"):
        _assemble_program([f"{label}:", "MOV R0, V0"])


def test_runner_rejects_data_and_code_symbol_collision() -> None:
    with pytest.raises(SimulationError, match=r"data/code symbol collision.*item"):
        _assemble_program(
            [
                "space:",
                "item = 00000001",
                "item:",
                "main:",
                "MOV R0, V0",
            ]
        )


@pytest.mark.parametrize("source", ["main:", "# comment only"])
def test_runner_rejects_programs_without_instructions(source: str) -> None:
    with pytest.raises(SimulationError, match="no instructions encoded"):
        _assemble_program(source.splitlines())


def test_runner_accepts_runtime_image_beyond_old_4k_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    image = bytes(4097)
    monkeypatch.setattr(runner_module.shutil, "which", lambda _name: "available")
    monkeypatch.setattr(
        runner_module, "_assemble_program", lambda _lines: (image, {})
    )

    loaded, labels = runner_module._prepare_run("ignored", 0, 0, 0, 16)

    assert loaded == image
    assert labels == {}


def test_runner_rejects_image_beyond_canonical_runtime_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    image = bytes(LOADER_MAX_PROGRAM_SIZE + 1)
    monkeypatch.setattr(runner_module.shutil, "which", lambda _name: "available")
    monkeypatch.setattr(
        runner_module, "_assemble_program", lambda _lines: (image, {})
    )

    with pytest.raises(
        SimulationError,
        match=rf"{len(image)} bytes.*maximum is {LOADER_MAX_PROGRAM_SIZE}",
    ):
        runner_module._prepare_run("ignored", 0, 0, 0, 16)


def test_generated_loader_uses_address_width_as_tighter_limit() -> None:
    address_capacity = 1 << 12
    with pytest.raises(
        ValueError,
        match=rf"{address_capacity + 1} bytes.*maximum is {address_capacity}",
    ):
        render_loader_sv(bytes(address_capacity + 1), addr_width=12)


def test_generated_loader_rejects_oversized_runtime_image() -> None:
    oversized = LOADER_MAX_PROGRAM_SIZE + 1
    with pytest.raises(
        ValueError,
        match=rf"{oversized} bytes.*maximum is {LOADER_MAX_PROGRAM_SIZE}",
    ):
        render_loader_sv(bytes(oversized), addr_width=16)

    loader = render_loader_sv(b"\0\0\0\0", addr_width=12)
    assert "logic [ADDR_WIDTH:0] load_addr" in loader
    assert "write_addr_ram <= load_addr[ADDR_WIDTH-1:0]" in loader


def test_hex_to_mif_32_bit_depth_counts_words_without_losing_bytes(tmp_path: Path) -> None:
    source = tmp_path / "program.hex"
    output = tmp_path / "program.mif"
    source.write_text("01\n02\n03\n04\n", encoding="ascii")

    result = hex_to_mif(source, output, width=32, max_depth=2)

    assert "DEPTH=2;" in result
    assert "04030201" in result
    assert output.read_text(encoding="ascii") == result


def test_hex_to_mif_refuses_to_truncate_program_or_halt_word(tmp_path: Path) -> None:
    source = tmp_path / "too-large.hex"
    output = tmp_path / "too-large.mif"
    source.write_text("\n".join(f"{value:02X}" for value in range(1, 9)), encoding="ascii")

    with pytest.raises(ValueError, match="refusing to truncate"):
        hex_to_mif(source, output, width=32, max_depth=2)

    assert not output.exists()


def test_snapshot_parser_preserves_unknown_register_values() -> None:
    output = "\n".join(
        [
            REGISTER_START,
            "R0=X",
            "R1=x (0xxxxx)",
            "PC=12 (0x000c)",
            "CPSR=0xxxxxxxxx",
            REGISTER_END,
            MEMORY_START,
            MEMORY_END,
        ]
    )

    registers, _, _, log = parse_snapshot_output(output, addr_width=16, data_width=8)

    assert registers["R0"] == {"dec": None, "hex": None}
    assert registers["R1"] == {"dec": None, "hex": None}
    assert registers["CPSR"] == {"dec": None, "hex": None}
    assert registers["PC"] == {"dec": 12, "hex": "000C"}
    assert log == ""


@pytest.mark.skipif(not _has_icarus(), reason="iverilog/vvp not available on PATH")
def test_snapshot_timeout_is_a_concise_error() -> None:
    with pytest.raises(SimulationError) as exc_info:
        run_snapshot("main:\n    B main\n", mem_start=0, mem_end=4, max_cycles=50)

    message = str(exc_info.value)
    assert message == "Simulation exceeded max_cycles=50 without halting"
    assert len(message) < 100


@pytest.mark.skipif(not _has_icarus(), reason="iverilog/vvp not available on PATH")
def test_stream_has_the_same_cycle_limit_as_snapshot() -> None:
    with pytest.raises(SimulationError, match="max_cycles=50"):
        list(
            stream_snapshot_events(
                "main:\n    B main\n",
                mem_start=0,
                mem_end=4,
                max_cycles=50,
            )
        )


@pytest.mark.skipif(not _has_icarus(), reason="iverilog/vvp not available on PATH")
def test_closing_stream_reaps_vvp_process(monkeypatch: pytest.MonkeyPatch) -> None:
    exit_codes: list[int | None] = []
    real_stop_process = runner_module._stop_process

    def recording_stop_process(proc: subprocess.Popen[str]) -> None:
        real_stop_process(proc)
        exit_codes.append(proc.poll())

    monkeypatch.setattr(runner_module, "_stop_process", recording_stop_process)
    events = stream_snapshot_events(
        "main:\n    B main\n",
        mem_start=0,
        mem_end=4,
        max_cycles=1_000_000,
    )
    try:
        assert next(events)["type"] == "start"
        next(events)
    finally:
        events.close()

    assert exit_codes
    assert exit_codes[-1] is not None


@pytest.mark.skipif(not _has_icarus(), reason="iverilog/vvp not available on PATH")
def test_runtime_ram_outside_loaded_image_starts_zeroed() -> None:
    result = run_snapshot(
        "main:\n    MOV R1, V5\n    LSL R1, V10\n    MOV R0, [R1]\n",
        mem_start=5000,
        mem_end=5000,
        max_cycles=10_000,
    )

    assert result["registers"]["R0"] == {"dec": 0, "hex": "0000"}
    assert result["memory"] == [{"addr": 5000, "dec": 0, "hex": "00"}]
