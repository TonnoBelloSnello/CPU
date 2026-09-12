from __future__ import annotations

from .constants import CONDITION_SUFFIX_BY_CODE

CHUNK_BITS = 8
CHUNK_MASK = (1 << CHUNK_BITS) - 1
MAX_DIRECT_IMMEDIATE = 0xFFF


def is_constant_load(token: str) -> bool:
    return token.strip().startswith("=")


def constant_load_expression(token: str) -> str:
    return token.strip()[1:].strip()


def expand_constant_load(dest: str, value: int, condition: int) -> list[str]:
    if value < 0:
        raise ValueError(
            f"'=' constant must be non-negative (use MVN for a bitwise complement): {value}"
        )

    suffix = CONDITION_SUFFIX_BY_CODE.get(condition, "")
    if value <= MAX_DIRECT_IMMEDIATE:
        return [f"MOV{suffix} {dest}, V{value}"]

    chunks: list[int] = []
    remaining = value
    while remaining:
        chunks.append(remaining & CHUNK_MASK)
        remaining >>= CHUNK_BITS
    chunks.reverse()

    lines = [f"MOV{suffix} {dest}, V{chunks[0]}"]
    for chunk in chunks[1:]:
        lines.append(f"LSL{suffix} {dest}, V{CHUNK_BITS}")
        if chunk:
            lines.append(f"ORR{suffix} {dest}, {dest}, V{chunk}")
    return lines


def constant_load_word_count(value: int) -> int:
    return len(expand_constant_load("R0", value, 0))
