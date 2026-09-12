from __future__ import annotations

import re
import struct

import pytest
from conftest import ROOT

from src.cpu.simulation.emulator import CPUEmulator
from src.cpu.simulation.rtl_config import LOADER_MAX_PROGRAM_SIZE
from src.cpu.simulation.runner import _assemble_program

FB_WIDTH = 160
FB_HEIGHT = 120
PALETTE_SIZE = 128
INTERIOR = 1

PROGRAM_PATH = ROOT / "programs" / "mandelbrot.de1"


def _assemble(source: str) -> tuple[bytes, dict[str, int]]:
    return _assemble_program(source.splitlines())


def _run(
    source: str, *, key_mask: int = 0, max_cycles: int
) -> tuple[CPUEmulator, dict[str, int], int]:
    image, labels = _assemble(source)
    cpu = CPUEmulator(image, key_mask=key_mask)
    while not cpu.halted and cpu.cycles < max_cycles:
        cpu.step()
    assert cpu.halted, f"Mandelbrot demo exceeded {max_cycles} architectural cycles"
    return cpu, labels, len(image)


def _one_frame_source() -> str:
    source = PROGRAM_PATH.read_text(encoding="utf-8")
    assert source.count("    B frame_loop") == 1, "frame loop marker moved"
    return source.replace("    B frame_loop", "    B test_end", 1) + "\ntest_end:\n"


def _after_input_source() -> str:
    source = PROGRAM_PATH.read_text(encoding="utf-8")
    assert source.count("    BL render") == 1
    return source.replace("    BL render", "    B test_end", 1) + "\ntest_end:\n"


def _seed(source: str, *, step: float | None = None, center: float | None = None) -> str:
    """Rewrite the view main: installs, to start a run somewhere else."""
    if step is not None:
        source, hits = re.subn(
            r"FMOV R0, F0\.01875\n    SAVEM R0, \[step\]",
            f"FMOV R0, F{step}\n    SAVEM R0, [step]",
            source,
            count=1,
        )
        assert hits == 1, "step seed moved"
    if center is not None:
        source, hits = re.subn(
            r"FMOV R0, F-0\.75\n    SAVEM R0, \[center_real\]",
            f"FMOV R0, F{center}\n    SAVEM R0, [center_real]",
            source,
            count=1,
        )
        assert hits == 1, "centre seed moved"
    return source


@pytest.fixture(scope="module")
def first_frame() -> tuple[CPUEmulator, dict[str, int], int]:
    return _run(_one_frame_source(), max_cycles=2_000_000)


def _fp16(memory: bytearray, address: int) -> float:
    bits = memory[address] | (memory[address + 1] << 8)
    return struct.unpack("<e", struct.pack("<H", bits))[0]


def _channels(colour: int) -> tuple[int, int, int]:
    return (colour >> 5, (colour >> 2) & 7, colour & 3)


def _colour_distance(left: int, right: int) -> int:
    return sum(abs(a - b) for a, b in zip(_channels(left), _channels(right)))


def test_first_frame_is_complete_colourful_and_fast(first_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    cpu, _labels, image_size = first_frame
    pixels = cpu.framebuffer

    assert image_size <= LOADER_MAX_PROGRAM_SIZE, "demo exceeds the runtime loader"
    assert all(pixels), "a zero pixel means the frame is black or incomplete"
    assert len(set(pixels)) >= 30, "the escape-time gradient has collapsed"
    assert 2_500 < pixels.count(INTERIOR) < 7_000, "the Mandelbrot silhouette disappeared"
    assert cpu.instructions_retired < 1_200_000


def test_shading_is_continuous_rather_than_speckled(
    first_frame: tuple[CPUEmulator, dict[str, int], int],
) -> None:
    """Smooth escape counts mean neighbours usually share a colour.

    Banding on the raw integer iteration count, or any per-pixel noise mixed
    into the palette index, pushes this well past 90%.
    """
    cpu, _labels, _image_size = first_frame
    pixels = cpu.framebuffer

    pairs = changes = 0
    for y in range(FB_HEIGHT):
        for x in range(FB_WIDTH - 1):
            left = pixels[y * FB_WIDTH + x]
            right = pixels[y * FB_WIDTH + x + 1]
            if left == INTERIOR or right == INTERIOR:
                continue
            pairs += 1
            changes += left != right

    assert pairs > 10_000
    assert changes / pairs < 0.55


def test_frame_has_exact_real_axis_symmetry(first_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    cpu, _labels, _image_size = first_frame
    pixels = cpu.framebuffer

    mismatches = [
        (x, y)
        for y in range(FB_HEIGHT // 2)
        for x in range(FB_WIDTH)
        if pixels[y * FB_WIDTH + x]
        != pixels[(FB_HEIGHT - 1 - y) * FB_WIDTH + x]
    ]
    assert not mismatches, f"conjugate Mandelbrot pixels differ, e.g. {mismatches[:5]}"


def test_opening_view_contains_known_mandelbrot_points(first_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    cpu, labels, _image_size = first_frame
    pixels = cpu.framebuffer

    assert _fp16(cpu.memory, labels["center_real"]) == pytest.approx(-0.75, abs=2e-4)
    assert _fp16(cpu.memory, labels["step"]) == pytest.approx(0.01875, abs=2e-4)

    assert pixels[59 * FB_WIDTH + 66] == INTERIOR
    assert pixels[59 * FB_WIDTH + 119] == INTERIOR
    assert pixels[59 * FB_WIDTH + 146] != INTERIOR
    assert pixels[0] != INTERIOR
    assert pixels[-1] != INTERIOR


def test_boot_generates_a_closed_rgb332_gradient(first_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    cpu, labels, _image_size = first_frame
    palette = list(cpu.memory[labels["palette"] : labels["palette"] + PALETTE_SIZE])

    assert len(set(palette)) >= 28
    assert 0 not in palette
    assert INTERIOR not in palette, "the interior colour has to stay the set's alone"
    assert set(cpu.framebuffer) <= set(palette) | {INTERIOR}

    assert {colour >> 5 for colour in palette} == set(range(8))
    assert {colour & 3 for colour in palette} == set(range(4))
    assert {(colour >> 2) & 7 for colour in palette} >= set(range(1, 8))

    steps = [
        _colour_distance(palette[index], palette[index + 1])
        for index in range(PALETTE_SIZE - 1)
    ]
    assert _colour_distance(palette[-1], palette[0]) <= max(steps), (
        "the palette is indexed cyclically, so its two ends have to meet"
    )

    longest = 1
    run = 1
    for index in range(1, PALETTE_SIZE):
        run = run + 1 if palette[index] == palette[index - 1] else 1
        longest = max(longest, run)
    assert longest <= 12, "a long plateau reads as a band, not a gradient"


@pytest.mark.parametrize(
    ("key_mask", "expected_center", "expected_step"),
    [
        (0b0000, -0.750, 0.01875),
        (0b0001, -0.900, 0.01875),
        (0b1000, -0.600, 0.01875),
        (0b1001, -0.750, 0.01875),
        (0b0010, -0.750, 0.01500),
        (0b0100, -0.750, 0.01875),
        (0b0110, -0.750, 0.01875),
        (0b1111, -0.750, 0.01875),
    ],
)
def test_key_controls_and_chords(
    key_mask: int, expected_center: float, expected_step: float
) -> None:
    cpu, labels, _image_size = _run(
        _after_input_source(), key_mask=key_mask, max_cycles=400_000
    )

    assert _fp16(cpu.memory, labels["center_real"]) == pytest.approx(
        expected_center, abs=5e-4
    )
    assert _fp16(cpu.memory, labels["step"]) == pytest.approx(expected_step, abs=2e-4)
    assert "color_phase" not in labels
    assert cpu.memory[labels["keys"]] == key_mask
    assert cpu.led == key_mask
    assert cpu.registers[13] == 0xFF00, "register-list PUSH/POP leaked stack space"


@pytest.mark.parametrize(
    ("step", "expected_limit"),
    [
        (0.01875, 64),
        (0.00800, 96),
        (0.00400, 128),
        (0.00200, 160),
        (0.00100, 224),
    ],
)
def test_iteration_budget_follows_the_zoom(step: float, expected_limit: int) -> None:
    cpu, labels, _image_size = _run(
        _seed(_after_input_source(), step=step), max_cycles=400_000
    )

    assert cpu.memory[labels["iter_limit"]] == expected_limit


@pytest.mark.parametrize(
    ("center", "expected_step"),
    [
        (-1.75, 1.75 * 0.0013),   # far from the origin: binary16 gives up sooner
        (-0.25, 0.0025 * 0.8),    # near it: the plain zoom ratio still applies
    ],
)
def test_zoom_floor_follows_binary16_resolution(center: float, expected_step: float) -> None:
    cpu, labels, _image_size = _run(
        _seed(_after_input_source(), step=0.0025, center=center),
        key_mask=0b0010,
        max_cycles=400_000,
    )

    assert _fp16(cpu.memory, labels["step"]) == pytest.approx(expected_step, rel=2e-3)


def test_zoom_in_never_coarsens_a_view_already_past_the_floor() -> None:
    cpu, labels, _image_size = _run(
        _seed(_after_input_source(), step=0.0002, center=-1.75),
        key_mask=0b0010,
        max_cycles=400_000,
    )

    assert _fp16(cpu.memory, labels["step"]) == pytest.approx(0.0002, rel=2e-3)
