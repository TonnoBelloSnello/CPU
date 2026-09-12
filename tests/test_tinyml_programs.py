from __future__ import annotations

import json
import shutil

import pytest
from conftest import ROOT, framebuffer_map, memory_map, register_value

from scripts.ml.tinyml_export import compile_model
from src.cpu.encoder.assemble import assemble
from src.cpu.encoder.steps.directives import expand_includes
from src.cpu.simulation.emulator import CPUEmulator
from src.cpu.simulation.runner import _assemble_program, run_snapshot
from src.cpu.simulation.snapshot import Snapshot

BENCH_PATH = ROOT / "programs" / "tinyml_bench.de1"
DIGITS_PATH = ROOT / "programs" / "tinyml_digits.de1"
DIGITS_MODEL = ROOT / "scripts" / "models" / "digits8x8" / "model.json"

CLASSES = 10
INPUTS = 64


def _assemble(source: str) -> tuple[bytes, dict[str, int]]:
    return _assemble_program(source.splitlines())


def _fast_memory(source: str, *, max_cycles: int) -> tuple[dict[int, int], dict[str, int], CPUEmulator]:
    image, labels = _assemble(source)
    cpu = CPUEmulator(image)
    while not cpu.halted and cpu.cycles < max_cycles:
        cpu.step()
    assert cpu.halted, f"program did not halt within {max_cycles} architectural steps"
    return dict(enumerate(cpu.memory)), labels, cpu


def _rtl_memory(
    source: str, *, mem_end: int, max_cycles: int
) -> tuple[dict[int, int], Snapshot]:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")
    snapshot = run_snapshot(source, mem_start=0, mem_end=mem_end, max_cycles=max_cycles)
    return memory_map(snapshot), snapshot


def _signed_byte(value: int) -> int:
    return value - 256 if value > 127 else value


def test_generated_digits_program_matches_its_model() -> None:
    model = json.loads(DIGITS_MODEL.read_text(encoding="utf-8"))
    assert compile_model(model) == DIGITS_PATH.read_text(encoding="utf-8"), (
        "programs/tinyml_digits.de1 is stale; regenerate it with\n"
        "  uv run python scripts/ml/tinyml_export.py scripts/models/digits8x8/model.json "
        "-o programs/tinyml_digits.de1"
    )


def test_digit_classifier_reproduces_the_reference_scores() -> None:
    model = json.loads(DIGITS_MODEL.read_text(encoding="utf-8"))
    sample = [_signed_byte(v) for v in model["input"]["values"]]
    weights = [_signed_byte(v) for v in model["layers"][0]["weights"]]
    expected = [
        sum(a * b for a, b in zip(sample, weights[c * INPUTS : (c + 1) * INPUTS], strict=True))
        for c in range(CLASSES)
    ]
    assert max(range(CLASSES), key=lambda c: expected[c]) == 3

    source = DIGITS_PATH.read_text(encoding="utf-8")
    memory, labels, cpu = _fast_memory(source, max_cycles=200_000)
    logits_base = labels["match_out"]
    produced = [_signed_byte(memory[logits_base + c]) for c in range(CLASSES)]

    assert produced == expected
    assert cpu.hex == 3
    assert cpu.led == 3


def test_digit_classifier_agrees_between_the_rtl_and_the_emulator() -> None:
    source = DIGITS_PATH.read_text(encoding="utf-8")
    fast_memory, labels, _ = _fast_memory(source, max_cycles=200_000)
    rtl_memory, snapshot = _rtl_memory(source, mem_end=1024, max_cycles=200_000)

    base = labels["match_out"]
    assert [rtl_memory[base + c] for c in range(CLASSES)] == [
        fast_memory[base + c] for c in range(CLASSES)
    ]
    assert register_value(snapshot, "HEX") == 3


def test_benchmark_three_implementations_agree() -> None:
    source = BENCH_PATH.read_text(encoding="utf-8")
    memory, labels, _ = _fast_memory(source, max_cycles=500_000)

    scalar = [memory[labels["out_s"] + i] for i in range(CLASSES)]
    vector = [memory[labels["out_v"] + i] for i in range(CLASSES)]
    engine = [memory[labels["out_e"] + i] for i in range(CLASSES)]

    assert scalar == vector == engine
    assert len(set(scalar)) > 1
    assert memory[labels["verdict"]] == 1


def test_benchmark_records_a_speedup_under_the_cycle_accurate_engine() -> None:
    source = BENCH_PATH.read_text(encoding="utf-8")
    memory, snapshot = _rtl_memory(source, mem_end=900, max_cycles=500_000)
    _, labels = _assemble(source)

    def elapsed(name: str) -> int:
        base = labels[name]
        return memory[base] | (memory[base + 1] << 8)

    scalar, vector, engine = elapsed("t_scalar"), elapsed("t_vector"), elapsed("t_engine")

    assert memory[labels["verdict"]] == 1
    assert 0 < engine < vector < scalar, (scalar, vector, engine)
    assert scalar / 640 > 8
    assert engine / 640 < 2
    assert register_value(snapshot, "LE") == 1


VGA_PATH = ROOT / "programs" / "tinyml_vga_digits.de1"
WHITE, GREEN, RED = 0xFF, 0x1C, 0xE0
NOISE_SEED, NOISE_MASK = 0x27EF, 0x0F


def _vga_source() -> str:
    return "\n".join(expand_includes(
        VGA_PATH.read_text(encoding="utf-8").splitlines(), VGA_PATH.parent
    ))


def test_vga_include_and_inline_source_have_identical_images() -> None:
    demo = assemble(VGA_PATH.read_text(encoding="utf-8").splitlines(), VGA_PATH.parent)
    inline = assemble(_vga_source().splitlines())
    assert demo.to_bytes() == inline.to_bytes()
    assert demo.symbols == inline.symbols


def _stencil_table(source: str) -> list[int]:
    line = next(
        text for text in source.splitlines() if text.strip().startswith("stencils")
    )
    body = line.split("=", 1)[1].strip()[1:-1]
    return [int(v) for chunk in body.split("},{") for v in chunk.strip("{}").split(",")]


def _xorshift16(state: int) -> int:
    state ^= (state << 7) & 0xFFFF
    state ^= state >> 9
    state ^= (state << 8) & 0xFFFF
    return state & 0xFFFF


def test_vga_demo_stencils_match_the_model() -> None:
    model = json.loads(DIGITS_MODEL.read_text(encoding="utf-8"))
    assert _stencil_table(_vga_source()) == model["layers"][0]["weights"]


def test_vga_demo_classifies_every_digit_and_paints_no_red() -> None:
    source = _vga_source()
    image, _ = _assemble(source)
    cpu = CPUEmulator(image)
    while not cpu.halted and cpu.cycles < 3_000_000:
        cpu.step()
    assert cpu.halted

    colours = {}
    for value in cpu.framebuffer:
        if value:
            colours[value] = colours.get(value, 0) + 1

    assert RED not in colours, "a digit was misclassified"
    assert set(colours) == {WHITE, GREEN}
    assert colours[WHITE] % 4 == 0
    assert colours[WHITE] > 400
    assert colours[GREEN] % 4 == 0
    assert colours[GREEN] > 400


def test_vga_demo_noise_is_deterministic_and_within_its_budget() -> None:
    source = _vga_source()
    stencils = [_signed_byte(v) for v in _stencil_table(source)]

    state = NOISE_SEED
    flips_per_digit = []
    expected_last = []
    for digit in range(CLASSES):
        sample = stencils[digit * INPUTS : (digit + 1) * INPUTS]
        noisy, flips = [], 0
        for value in sample:
            state = _xorshift16(state)
            if state & NOISE_MASK:
                noisy.append(value)
            else:
                noisy.append(-value)
                flips += 1
        flips_per_digit.append(flips)
        expected_last = noisy

    assert all(4 <= flips <= 10 for flips in flips_per_digit), flips_per_digit

    image, labels = _assemble(source)
    cpu = CPUEmulator(image)
    while not cpu.halted and cpu.cycles < 3_000_000:
        cpu.step()
    base = labels["sample"]
    produced = [_signed_byte(cpu.memory[base + i]) for i in range(INPUTS)]
    assert produced == expected_last


def test_vga_demo_agrees_between_the_rtl_and_the_emulator() -> None:
    source = _vga_source()
    image, _ = _assemble(source)
    cpu = CPUEmulator(image)
    while not cpu.halted and cpu.cycles < 3_000_000:
        cpu.step()
    fast = {index: value for index, value in enumerate(cpu.framebuffer) if value}

    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")
    snapshot = run_snapshot(source, mem_start=0, mem_end=16, max_cycles=2_000_000)
    rtl = framebuffer_map(snapshot)

    assert rtl == fast
