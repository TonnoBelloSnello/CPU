from __future__ import annotations

import struct

import pytest
from conftest import ROOT, framebuffer_map, memory_map

from src.cpu.simulation.runner import run_snapshot

FB_WIDTH = 160
FB_HEIGHT = 120
SIN_BASE = 0x9400
TEX_BASE = 0x8000

PROGRAM_PATH = ROOT / "programs" / "raycaster.de1"


def _one_frame_source() -> str:
    src = PROGRAM_PATH.read_text(encoding="utf-8")
    assert "    B frame_loop" in src, "frame loop marker moved"
    return src.replace("    B frame_loop", "    B test_end", 1) + "\ntest_end:\n"


@pytest.fixture(scope="module")
def frame() -> dict[int, int]:
    result = run_snapshot(_one_frame_source(), mem_start=0, mem_end=4,
                          max_cycles=4_000_000)
    return framebuffer_map(result)


@pytest.fixture(scope="module")
def no_hud_frame() -> dict[int, int]:
    src = _one_frame_source()
    assert "    BL draw_hud" in src
    src = src.replace("    BL draw_hud", "", 1)
    result = run_snapshot(src, mem_start=0, mem_end=4, max_cycles=4_000_000)
    return framebuffer_map(result)


@pytest.fixture(scope="module")
def boot_memory() -> dict[int, int]:
    src = PROGRAM_PATH.read_text(encoding="utf-8")
    src = src.replace("frame_loop:\n    BL read_input",
                      "frame_loop:\n    B test_end\n    BL read_input", 1)
    src += "\ntest_end:\n"
    result = run_snapshot(src, mem_start=TEX_BASE, mem_end=SIN_BASE + 512,
                          max_cycles=2_000_000)
    return memory_map(result)


def px(frame: dict[int, int], x: int, y: int) -> int:
    return frame.get(y * FB_WIDTH + x, 0)


HUD_W = 44  # minimap (32) plus the compass column
HUD_H = 32


def in_hud(x: int, y: int) -> bool:
    return x < HUD_W and y < HUD_H


def test_every_viewport_pixel_is_painted(frame: dict[int, int]) -> None:
    missing = [
        (x, y)
        for x in range(FB_WIDTH)
        for y in range(FB_HEIGHT)
        if not in_hud(x, y) and (y * FB_WIDTH + x) not in frame
    ]
    assert not missing, f"{len(missing)} unpainted viewport pixels, e.g. {missing[:5]}"


def test_3d_view_never_paints_into_the_hud_block(no_hud_frame: dict[int, int]) -> None:
    painted = [
        (x, y)
        for x in range(HUD_W)
        for y in range(HUD_H)
        if (y * FB_WIDTH + x) in no_hud_frame
    ]
    assert not painted, (
        f"the 3D view wrote {len(painted)} pixels inside the HUD block, "
        f"e.g. {painted[:5]} -- the HUD will flicker"
    )


def test_sin_table_matches_taylor_series(boot_memory: dict[int, int]) -> None:
    import math

    worst = 0.0
    for i in range(256):
        lo = boot_memory.get(SIN_BASE + 2 * i, 0)
        hi = boot_memory.get(SIN_BASE + 2 * i + 1, 0)
        got = struct.unpack("<e", struct.pack("<H", (hi << 8) | lo))[0]
        worst = max(worst, abs(got - math.sin(i * 2 * math.pi / 256)))
    assert worst < 2e-3, f"sin table drifted, worst error {worst}"


def test_textures_are_generated_and_distinct(boot_memory: dict[int, int]) -> None:
    palettes = []
    for t in range(4):
        vals = [boot_memory.get(TEX_BASE + t * 1024 + i, 0) for i in range(1024)]
        assert len(set(vals)) >= 3, f"texture {t} is nearly flat"
        palettes.append(frozenset(vals))
    assert len(set(palettes)) == 4, "textures are not distinguishable from each other"


def test_horizon_splits_sky_from_floor(frame: dict[int, int]) -> None:
    ceiling = [px(frame, x, 2) for x in range(70, 92)]
    floor = [px(frame, x, 117) for x in range(70, 92)]
    assert max(ceiling) < 64, f"ceiling band is not dark: {max(ceiling)}"
    assert min(floor) > 64, f"floor band is not lit: {min(floor)}"


def test_walls_appear_on_both_sides(frame: dict[int, int]) -> None:
    def reds(x0: int, x1: int) -> int:
        return sum(
            1
            for x in range(x0, x1)
            for y in range(30, 90)
            if (px(frame, x, y) >> 5) >= 3
        )

    left, right = reds(0, 60), reds(100, 160)
    assert left > 400, f"left wall missing ({left} textured pixels)"
    assert right > 400, f"right wall missing ({right} textured pixels)"


def test_minimap_is_drawn_in_the_corner(frame: dict[int, int]) -> None:
    cells = [px(frame, x, y) for x in range(32) for y in range(32)]
    assert any(c == 0 for c in cells), "minimap shows no open corridor cells"
    assert any(c != 0 for c in cells), "minimap shows no walls"
    assert px(frame, 1, 1) == 255, "player marker missing at the spawn cell"
