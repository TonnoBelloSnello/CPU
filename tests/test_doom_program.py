from __future__ import annotations

import math
import struct

import pytest
from conftest import ROOT

from src.cpu.simulation.emulator import CPUEmulator
from src.cpu.simulation.rtl_config import LOADER_MAX_PROGRAM_SIZE
from src.cpu.simulation.runner import _assemble_program

FB_WIDTH = 160
FB_HEIGHT = 120

BAND_Y = 88  # status bar top row
NOTCH_X0 = 75  # weapon-barrel notch, columns 75..85
NOTCH_X1 = 86
NOTCH_Y = 80

MAP_BASE = 0x9000
SIN_BASE = 0x9400
TEX_BASE = 0x8000
ZBUF_BASE = 0x9660
SPR_BASE = 0x9800
SPR_SIZE = 1024
GUN_BASE = 0xB000
GUN_H = 40
ENT_BASE = 0xB600
ENT_SIZE = 16
MAX_ENT = 28

K_IMP, K_MED, K_AMMO, K_DEAD, K_BALL = 1, 2, 3, 4, 5

KEY_LEFT, KEY_FWD, KEY_BACK, KEY_RIGHT = 0b0001, 0b0010, 0b0100, 0b1000
KEY_FIRE = KEY_FWD | KEY_BACK

PROGRAM_PATH = ROOT / "programs" / "doom.de1"

ZBUF_STUB = """
zz_zbuf_far:
    MOV R0, =ZBUF_BASE
    MOV R1, V0
    FMOV R2, F99.0
zz_zbuf_loop:
    SAVEM R2, [R0]
    ADD R0, R0, V2
    ADD R1, R1, V1
    CMP R1, V160
    BLT zz_zbuf_loop
    MOV PC, R14
"""


def _assemble(source: str) -> tuple[bytes, dict[str, int]]:
    return _assemble_program(source.splitlines())


def _source() -> str:
    return PROGRAM_PATH.read_text(encoding="utf-8")


def _budgeted(source: str, frames: int) -> str:
    assert source.count("    B frame_loop") == 1, "frame loop marker moved"
    if frames == 1:
        return source.replace("    B frame_loop", "    B zz_end", 1) + "\nzz_end:\n"
    assert 1 < frames < 256
    source = source.replace(
        "    B frame_loop",
        "\n".join(
            [
                "    MOV R0, [zz_budget]",
                "    SUB R0, R0, V1",
                "    SAVE R0, [zz_budget]",
                "    CMP R0, V0",
                "    BNE frame_loop",
                "    B zz_end",
            ]
        ),
        1,
    )
    assert source.count("space:\n") == 1
    source = source.replace("space:\n", f"space:\n    zz_budget = {frames:08b}\n", 1)
    return source + "\nzz_end:\n"


def _inject(source: str, setup: str) -> str:
    assert source.count("frame_loop:\n") == 1, "frame loop label moved"
    return source.replace("frame_loop:\n", setup + "\nframe_loop:\n", 1)


def _frame_source(frames: int = 1, setup: str = "", *, drop: tuple[str, ...] = ()) -> str:
    source = _source()
    for call in drop:
        line = f"    BL {call}\n"
        assert source.count(line) == 1, f"{call} call site moved"
        source = source.replace(line, "", 1)
    if setup:
        source = _inject(source, setup)
    return _budgeted(source, frames)


def _logic_source(frames: int, setup: str = "") -> str:
    source = _source()
    assert source.count("    BL render\n") == 1
    source = source.replace("    BL render\n", "    BL zz_zbuf_far\n", 1)
    for call in ("render_sprites", "draw_weapon", "draw_hud", "hud_init"):
        line = f"    BL {call}\n"
        assert source.count(line) == 1, f"{call} call site moved"
        source = source.replace(line, "", 1)
    if setup:
        source = _inject(source, setup)
    return _budgeted(source + ZBUF_STUB, frames)


def _run(source: str, *, key_mask: int = 0, max_cycles: int) -> tuple[CPUEmulator, dict[str, int]]:
    image, labels = _assemble(source)
    cpu = CPUEmulator(image, key_mask=key_mask)
    while not cpu.halted and cpu.cycles < max_cycles:
        cpu.step()
    assert cpu.halted, f"demo exceeded {max_cycles} architectural cycles"
    return cpu, labels


def _place(slot: int, kind: int, x: float, y: float, *, awake: int = 1, timer: int = 0) -> str:
    return f"""
    MOV R0, =ENT_BASE + {slot} * ENT_SIZE
    MOV R1, V{kind}
    SAVE R1, [R0]
    MOV R1, V100
    ADD R2, R0, V1
    SAVE R1, [R2]
    MOV R1, V{awake}
    ADD R2, R0, V2
    SAVE R1, [R2]
    MOV R1, V{timer}
    ADD R2, R0, V3
    SAVE R1, [R2]
    FMOV R1, F{x}
    ADD R2, R0, V4
    SAVEM R1, [R2]
    FMOV R1, F{y}
    ADD R2, R0, V6
    SAVEM R1, [R2]
"""


def _fp16(memory: bytearray, address: int) -> float:
    bits = memory[address] | (memory[address + 1] << 8)
    return struct.unpack("<e", struct.pack("<H", bits))[0]


def _entities(memory: bytearray) -> list[tuple[int, int, int, float, float]]:
    live = []
    for slot in range(MAX_ENT):
        base = ENT_BASE + slot * ENT_SIZE
        if memory[base]:
            live.append(
                (slot, memory[base], memory[base + 1],
                 _fp16(memory, base + 4), _fp16(memory, base + 6))
            )
    return live


def px(frame: bytearray, x: int, y: int) -> int:
    return frame[y * FB_WIDTH + x]


@pytest.fixture(scope="module")
def opening_frame() -> tuple[CPUEmulator, dict[str, int], int]:
    image, _ = _assemble(_source())
    cpu, labels = _run(_frame_source(1), max_cycles=4_000_000)
    return cpu, labels, len(image)


@pytest.fixture(scope="module")
def world_only_frame() -> CPUEmulator:
    cpu, _ = _run(
        _frame_source(1, drop=("draw_weapon", "draw_hud", "hud_init")),
        max_cycles=4_000_000,
    )
    return cpu


@pytest.fixture(scope="module")
def boot_memory() -> bytearray:
    source = _source()
    assert source.count("frame_loop:\n    BL read_input") == 1
    source = source.replace(
        "frame_loop:\n    BL read_input", "frame_loop:\n    B zz_end\n    BL read_input", 1
    )
    cpu, _ = _run(source + "\nzz_end:\n", max_cycles=3_000_000)
    return cpu.memory


def test_program_fits_the_runtime_loader(opening_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    _cpu, _labels, image_size = opening_frame
    assert image_size <= LOADER_MAX_PROGRAM_SIZE


def test_every_pixel_is_painted(opening_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    cpu, _labels, _size = opening_frame
    holes = [
        (i % FB_WIDTH, i // FB_WIDTH)
        for i, value in enumerate(cpu.framebuffer)
        if value == 0
    ]
    assert not holes, f"{len(holes)} unpainted pixels, e.g. {holes[:5]}"


def test_world_pass_stays_inside_its_viewport(world_only_frame: CPUEmulator) -> None:
    frame = world_only_frame.framebuffer
    band = [
        (x, y)
        for y in range(BAND_Y, FB_HEIGHT)
        for x in range(FB_WIDTH)
        if px(frame, x, y)
    ]
    assert not band, f"world pass wrote {len(band)} pixels into the status bar, e.g. {band[:5]}"

    notch = [
        (x, y)
        for y in range(NOTCH_Y, BAND_Y)
        for x in range(NOTCH_X0, NOTCH_X1)
        if px(frame, x, y)
    ]
    assert not notch, f"world pass wrote {len(notch)} pixels into the barrel notch"

    holes = [
        (x, y)
        for y in range(BAND_Y)
        for x in range(FB_WIDTH)
        if not px(frame, x, y)
        and not (y >= NOTCH_Y and NOTCH_X0 <= x < NOTCH_X1)
    ]
    assert not holes, f"{len(holes)} unpainted viewport pixels, e.g. {holes[:5]}"


def test_horizon_splits_sky_from_floor(opening_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    frame = opening_frame[0].framebuffer
    ceiling = [px(frame, x, 2) for x in range(70, 92)]
    floor = [px(frame, x, BAND_Y - 1) for x in range(96, 120)]
    assert max(ceiling) < 32, f"ceiling band is not dark: {max(ceiling)}"
    assert min(floor) > 64, f"floor band is not lit: {min(floor)}"


def test_walls_appear_on_both_sides(opening_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    frame = opening_frame[0].framebuffer

    def reds(x0: int, x1: int) -> int:
        return sum(
            1
            for x in range(x0, x1)
            for y in range(20, 70)
            if (px(frame, x, y) >> 5) >= 3
        )

    left, right = reds(0, 60), reds(100, 160)
    assert left > 300, f"left wall missing ({left} textured pixels)"
    assert right > 300, f"right wall missing ({right} textured pixels)"


def test_status_bar_shows_the_minimap_and_readouts(opening_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    cpu, _labels, _size = opening_frame
    frame = cpu.framebuffer

    cells = [px(frame, x, y) for x in range(32) for y in range(BAND_Y, FB_HEIGHT)]
    assert cells.count(37) > 100, "minimap shows no open corridor cells"
    assert any(c in (164, 146, 173, 46) for c in cells), "minimap shows no walls"
    assert 255 in cells, "player marker missing from the minimap"

    right = [px(frame, x, y) for x in range(96, 160) for y in range(BAND_Y, FB_HEIGHT)]
    assert right.count(73) > 800, "right panel background missing"
    assert right.count(182) > 40, "right panel labels missing"

    barrel = [px(frame, x, y) for x in range(NOTCH_X0, NOTCH_X1) for y in range(NOTCH_Y, BAND_Y)]
    assert all(barrel), "the barrel notch is not fully covered by the weapon"


def test_zbuffer_records_every_column(opening_frame: tuple[CPUEmulator, dict[str, int], int]) -> None:
    cpu, _labels, _size = opening_frame
    depths = [_fp16(cpu.memory, ZBUF_BASE + 2 * x) for x in range(FB_WIDTH)]
    assert all(d >= 0.02 for d in depths), "a column left no wall distance"
    assert max(depths) > 3.0, "the spawn corridor should have a long sightline"


def test_steady_frames_never_write_a_pixel_twice_in_two_colours() -> None:
    image, labels = _assemble(_frame_source(4))
    cpu = CPUEmulator(image, key_mask=KEY_FWD)
    frame_loop = labels["frame_loop"]

    frames: list[dict[int, list[int]]] = []
    current: dict[int, list[int]] = {}
    started = False
    while not cpu.halted and cpu.cycles < 16_000_000:
        if cpu.pc == frame_loop:
            if started:
                frames.append(current)
                current = {}
            started = True
        for event in cpu.step():
            if "addr" in event:
                current.setdefault(int(event["addr"]), []).append(int(event["color"]))
    frames.append(current)
    assert cpu.halted
    assert len(frames) >= 4

    for index, frame in enumerate(frames[1:], start=1):
        conflicts = {a: v for a, v in frame.items() if len(set(v)) > 1}
        readable = [(a % FB_WIDTH, a // FB_WIDTH, v) for a, v in sorted(conflicts.items())[:5]]
        assert not conflicts, f"frame {index} would flicker at {readable}"


def test_sin_table_matches_taylor_series(boot_memory: bytearray) -> None:
    worst = 0.0
    for i in range(256):
        got = _fp16(boot_memory, SIN_BASE + 2 * i)
        worst = max(worst, abs(got - math.sin(i * 2 * math.pi / 256)))
    assert worst < 2e-3, f"sin table drifted, worst error {worst}"


def test_wall_textures_are_generated_and_distinct(boot_memory: bytearray) -> None:
    palettes = []
    for t in range(4):
        values = list(boot_memory[TEX_BASE + t * 1024: TEX_BASE + (t + 1) * 1024])
        assert len(set(values)) >= 3, f"wall texture {t} is nearly flat"
        assert 0 not in values, f"wall texture {t} has a black texel"
        palettes.append(frozenset(values))
    assert len(set(palettes)) == 4, "wall textures are not distinguishable"


def test_sprite_frames_have_shape_and_transparency(boot_memory: bytearray) -> None:
    coverage = []
    for frame in range(6):
        values = list(boot_memory[SPR_BASE + frame * SPR_SIZE: SPR_BASE + (frame + 1) * SPR_SIZE])
        opaque = sum(1 for v in values if v)
        assert 40 < opaque < 900, f"sprite {frame} covers {opaque}/1024 texels"
        assert len(set(values)) >= 3, f"sprite {frame} is a flat silhouette"
        coverage.append(opaque)

    walk_a = boot_memory[SPR_BASE: SPR_BASE + SPR_SIZE]
    walk_b = boot_memory[SPR_BASE + SPR_SIZE: SPR_BASE + 2 * SPR_SIZE]
    assert walk_a != walk_b, "the two monster walk frames are identical"


def test_weapon_barrel_covers_the_notch(boot_memory: bytearray) -> None:
    for gx in range(NOTCH_X0 - 64, NOTCH_X1 - 64):
        for gy in range(BAND_Y - NOTCH_Y):
            texel = boot_memory[GUN_BASE + gx * GUN_H + gy]
            assert texel, f"weapon texel ({gx},{gy}) is transparent inside the notch"


def test_level_starts_with_monsters_and_supplies(boot_memory: bytearray) -> None:
    live = _entities(boot_memory)
    kinds = [kind for _slot, kind, _hp, _x, _y in live]
    assert kinds.count(K_IMP) == 6, "level 1 should field six monsters"
    assert kinds.count(K_MED) == 3
    assert kinds.count(K_AMMO) == 4

    for slot, kind, _hp, x, y in live:
        cell = boot_memory[MAP_BASE + int(y) * 32 + int(x)]
        assert cell == 0, f"entity {slot} (kind {kind}) spawned inside a wall"
        assert abs(x - 1.5) + abs(y - 1.5) > 8.0, f"entity {slot} spawned on top of the player"


@pytest.mark.parametrize(
    ("key_mask", "expect"),
    [
        (0, {"x": 1.5, "ang": 0, "ammo": 40}),
        (KEY_FWD, {"x": 3.9, "ang": 0, "ammo": 40}),
        (KEY_BACK, {"x": 1.14, "ang": 0, "ammo": 40}),
        (KEY_LEFT, {"x": 1.5, "ang": 40, "ammo": 40}),
        (KEY_RIGHT, {"x": 1.5, "ang": 216, "ammo": 40}),
        (KEY_FIRE, {"x": 1.5, "ang": 0, "ammo": 34}),
        (KEY_FIRE | KEY_RIGHT, {"x": 1.5, "ang": 216, "ammo": 34}),
    ],
)
def test_keys_and_chords(key_mask: int, expect: dict[str, float]) -> None:
    cpu, labels = _run(_logic_source(40), key_mask=key_mask, max_cycles=4_000_000)
    memory = cpu.memory
    assert _fp16(memory, labels["posx"]) == pytest.approx(expect["x"], abs=0.05)
    assert _fp16(memory, labels["posy"]) == pytest.approx(1.5, abs=0.05)
    assert memory[labels["pang"]] == expect["ang"]
    assert memory[labels["ammo"]] == expect["ammo"]


def test_backing_into_a_wall_stops_short_of_it() -> None:
    cpu, labels = _run(_logic_source(60), key_mask=KEY_BACK, max_cycles=6_000_000)
    assert _fp16(cpu.memory, labels["posx"]) > 1.10


def test_shooting_a_monster_ahead_kills_it_and_leaves_a_corpse() -> None:
    cpu, labels = _run(
        _logic_source(30, _place(0, K_IMP, 4.0, 1.5)),
        key_mask=KEY_FIRE,
        max_cycles=4_000_000,
    )
    memory = cpu.memory
    assert memory[labels["kills"]] == 1
    assert memory[labels["nimp"]] == 5, "the level's remaining-monster count did not drop"
    assert memory[ENT_BASE] == K_DEAD, "the dead monster left no corpse"
    assert memory[labels["ammo"]] < 40


def test_a_monster_beside_the_crosshair_is_not_hit() -> None:
    cpu, labels = _run(
        _logic_source(30, _place(0, K_IMP, 4.0, 4.2)),
        key_mask=KEY_FIRE,
        max_cycles=4_000_000,
    )
    assert cpu.memory[labels["kills"]] == 0
    assert cpu.memory[ENT_BASE] == K_IMP


def test_an_empty_gun_still_reaches_the_next_cell() -> None:
    empty = "    MOV R0, V0\n    SAVE R0, [ammo]\n"
    near, labels = _run(
        _logic_source(60, empty + _place(0, K_IMP, 2.6, 1.5)),
        key_mask=KEY_FIRE,
        max_cycles=6_000_000,
    )
    assert near.memory[labels["kills"]] == 1, "an empty gun cannot retire an adjacent monster"
    assert near.memory[labels["ammo"]] == 0, "punching consumed ammunition"

    far, labels = _run(
        _logic_source(60, empty + _place(0, K_IMP, 6.5, 1.5)),
        key_mask=KEY_FIRE,
        max_cycles=6_000_000,
    )
    assert far.memory[labels["kills"]] == 0, "the fist reached across the room"


def test_a_monster_closes_in_and_claws_the_player() -> None:
    cpu, labels = _run(
        _logic_source(60, _place(0, K_IMP, 3.2, 1.5)), max_cycles=6_000_000
    )
    memory = cpu.memory
    assert memory[labels["health"]] < 100, "the monster never landed a hit"
    assert _fp16(memory, ENT_BASE + 4) < 3.2, "the monster never advanced"
    assert memory[ENT_BASE + 2] == 1, "the monster should be awake"


def test_line_of_sight_gates_waking_a_monster() -> None:
    walled = """
    MOV R0, =MAP_BASE + 3 * 32 + 1
    MOV R1, V0
    SAVE R1, [R0]
    MOV R0, =MAP_BASE + 2 * 32 + 1
    MOV R1, V1
    SAVE R1, [R0]
"""
    opened = walled.replace("    MOV R1, V1\n    SAVE R1, [R0]\n",
                            "    MOV R1, V0\n    SAVE R1, [R0]\n")
    blocked, _ = _run(
        _logic_source(6, walled + _place(0, K_IMP, 1.5, 3.5, awake=0)), max_cycles=2_000_000
    )
    assert blocked.memory[ENT_BASE + 2] == 0, "a monster woke through a wall"

    visible, _ = _run(
        _logic_source(6, opened + _place(0, K_IMP, 1.5, 3.5, awake=0)), max_cycles=2_000_000
    )
    assert visible.memory[ENT_BASE + 2] == 1, "a monster in plain sight stayed asleep"


def test_walking_over_supplies_restores_health_and_ammo() -> None:
    setup = _place(0, K_MED, 3.0, 1.5, awake=0) + _place(1, K_AMMO, 3.6, 1.5, awake=0) + """
    MOV R0, V50
    SAVE R0, [health]
    MOV R0, V10
    SAVE R0, [ammo]
"""
    cpu, labels = _run(_logic_source(40, setup), key_mask=KEY_FWD, max_cycles=4_000_000)
    memory = cpu.memory
    assert memory[labels["health"]] == 75, "the medkit did not heal"
    assert memory[labels["ammo"]] == 25, "the ammo crate did not reload"
    assert memory[ENT_BASE] == 0
    assert memory[ENT_BASE + ENT_SIZE] == 0


def test_supplies_are_capped() -> None:
    setup = _place(0, K_MED, 3.0, 1.5, awake=0) + _place(1, K_AMMO, 3.6, 1.5, awake=0) + """
    MOV R0, V95
    SAVE R0, [ammo]
"""
    cpu, labels = _run(_logic_source(40, setup), key_mask=KEY_FWD, max_cycles=4_000_000)
    assert cpu.memory[labels["health"]] == 100
    assert cpu.memory[labels["ammo"]] == 99


def test_a_projectile_stops_at_a_wall() -> None:
    setup = """
    MOV R0, =MAP_BASE + 32 + 5
    MOV R1, V1
    SAVE R1, [R0]
""" + _place(0, K_BALL, 3.0, 1.5, timer=90) + """
    MOV R0, =ENT_BASE + 8
    FMOV R1, F0.13
    SAVEM R1, [R0]
    MOV R0, =ENT_BASE + 10
    MOV R1, V0
    SAVEM R1, [R0]
"""
    cpu, labels = _run(_logic_source(40, setup), max_cycles=4_000_000)
    assert cpu.memory[ENT_BASE] == 0, "the fireball flew through a wall"
    assert cpu.memory[labels["health"]] == 100, "a walled-off fireball still hurt the player"


def test_being_overwhelmed_ends_the_run() -> None:
    swarm = "".join(
        _place(slot, K_IMP, x, y)
        for slot, (x, y) in enumerate(
            [(2.4, 1.5), (1.5, 2.4), (2.3, 2.3), (2.45, 1.6), (1.6, 2.45), (2.2, 2.2)]
        )
    )
    cpu, labels = _run(_logic_source(220, swarm), max_cycles=20_000_000)
    memory = cpu.memory
    assert memory[labels["health"]] == 0, "health must land on exactly zero, not wrap"
    assert memory[labels["gstate"]] == 1, "the run should have ended"


def test_clearing_a_level_advances_to_a_harder_one() -> None:
    clear_all = _place(0, K_IMP, 4.0, 1.5) + """
    MOV R0, =ENT_BASE + ENT_SIZE
    MOV R1, V0
    MOV R2, V1
zz_clear:
    SAVE R1, [R0]
    ADD R0, R0, ENT_SIZE
    ADD R2, R2, V1
    CMP R2, V6
    BLT zz_clear
    MOV R0, V1
    SAVE R0, [nimp]
"""
    image, labels = _assemble(_logic_source(120, clear_all))
    cpu = CPUEmulator(image, key_mask=KEY_FIRE)

    cleared_at = None
    released_at = None
    first_map = None
    while not cpu.halted and cpu.cycles < 20_000_000:
        cpu.step()
        state = cpu.memory[labels["gstate"]]
        if cleared_at is None and state == 2:
            cleared_at = cpu.cycles
            first_map = bytes(cpu.memory[MAP_BASE: MAP_BASE + 1024])
            cpu.key_mask = 0
        elif cleared_at is not None and released_at is None and cpu.cycles > cleared_at + 60_000:
            assert cpu.memory[labels["gstate"]] == 2, "a held key restarted the level"
            released_at = cpu.cycles
            cpu.key_mask = KEY_LEFT

    assert cpu.halted
    assert cleared_at is not None, "killing the last monster did not clear the level"
    assert released_at is not None

    memory = cpu.memory
    assert memory[labels["gstate"]] == 0, "the next level never started"
    assert memory[labels["level"]] == 2
    assert memory[labels["nimp"]] == 8, "level 2 should field two more monsters"
    assert memory[labels["health"]] == 100, "clearing a level should top the player up"
    assert memory[labels["ammo"]] > 40
    assert bytes(memory[MAP_BASE: MAP_BASE + 1024]) != first_map, "the maze was not regenerated"
    assert _fp16(memory, labels["posx"]) == pytest.approx(1.5, abs=0.01)
    assert cpu.registers[13] == 0xFF00, "register-list PUSH/POP leaked stack space"
