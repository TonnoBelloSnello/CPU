from __future__ import annotations

import struct
import sys
import zlib
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ml.tiny_text import ALPHABET, KEYS, MAX_PROMPT, TextModel, generate  # noqa: E402
from src.cpu.encoder.assemble import AssembledProgram  # noqa: E402
from src.cpu.simulation.emulator import CPUEmulator  # noqa: E402
from src.cpu.simulation.rtl_config import VGA_FB_HEIGHT, VGA_FB_WIDTH  # noqa: E402

STEP_BUDGET = 2_000_000
SCREENSHOT_SCALE = 4


def await_input(cpu: CPUEmulator, *, max_steps: int = STEP_BUDGET) -> None:
    for _ in range(max_steps):
        if cpu.blocked_on_keys:
            return
        if cpu.halted:
            raise RuntimeError("interactive program halted unexpectedly")
        cpu.step()
    raise RuntimeError("interactive program did not return to the keyboard")


def press_key(cpu: CPUEmulator, symbols: dict[str, int], mask: int) -> None:
    cpu.key_mask = 0
    await_input(cpu)
    cpu.key_mask = mask
    for _ in range(STEP_BUDGET):
        cpu.step()
        if cpu.pc == symbols["release_keys"]:
            break
    else:
        raise RuntimeError("key action did not finish")
    cpu.key_mask = 0
    await_input(cpu)


def select_key(cpu: CPUEmulator, symbols: dict[str, int], index: int) -> None:
    if not 0 <= index < 32:
        raise ValueError("keyboard index must be 0..31")
    await_input(cpu)
    for _ in range(4):
        if cpu.memory[symbols["selected"]] // 8 == index // 8:
            break
        press_key(cpu, symbols, 2)
    for _ in range(8):
        if cpu.memory[symbols["selected"]] == index:
            return
        press_key(cpu, symbols, 8)
    raise RuntimeError("could not navigate to keyboard key")


def type_prompt(cpu: CPUEmulator, symbols: dict[str, int], prompt: str) -> None:
    if len(prompt) > MAX_PROMPT or any(c not in ALPHABET for c in prompt):
        raise ValueError("prompt must contain at most 24 supported characters")
    for char in prompt:
        select_key(cpu, symbols, KEYS.index(char))
        press_key(cpu, symbols, 4)


def write_png(
    framebuffer: Sequence[int], path: Path, *, scale: int = SCREENSHOT_SCALE
) -> None:
    rows = bytearray()
    for y in range(VGA_FB_HEIGHT):
        line = bytearray()
        for x in range(VGA_FB_WIDTH):
            pixel = framebuffer[y * VGA_FB_WIDTH + x] & 0xFF
            channels = bytes(
                (
                    (pixel >> 5) * 255 // 7,
                    ((pixel >> 2) & 7) * 255 // 7,
                    (pixel & 3) * 255 // 3,
                )
            )
            line += channels * scale
        for _ in range(scale):
            rows += b"\0" + line

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload)))

    header = struct.pack(
        ">IIBBBBB", VGA_FB_WIDTH * scale, VGA_FB_HEIGHT * scale, 8, 2, 0, 0, 0
    )
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def smoke_test(
    model: TextModel, program: AssembledProgram, prompt: str, screenshot: Path | None = None
) -> tuple[str, int]:
    cpu = CPUEmulator(program.to_bytes())
    symbols = program.symbols
    type_prompt(cpu, symbols, prompt)
    select_key(cpu, symbols, 31)
    press_key(cpu, symbols, 4)
    base, length = symbols["generated"], cpu.memory[symbols["output_len"]]
    actual = bytes(cpu.memory[base : base + length]).decode("ascii")
    if actual != generate(model, prompt):
        raise RuntimeError(f"CPU output differs from integer reference: {actual!r}")
    if screenshot is not None:
        write_png(cpu.framebuffer, screenshot)
    return actual, cpu.cycles
