from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

WORD_BYTES = 4


def _read_bytes(hex_file: Path) -> list[int]:
    values: list[int] = []
    for line_number, line in enumerate(hex_file.read_text(encoding="ascii").splitlines(), 1):
        token = line.strip()
        if not token:
            continue
        try:
            value = int(token, 16)
        except ValueError as exc:
            raise ValueError(f"Invalid hex byte on line {line_number}: {token!r}") from exc
        if not 0 <= value <= 0xFF:
            raise ValueError(f"Hex value on line {line_number} is not a byte: {token!r}")
        values.append(value)
    return values


def _with_single_halt_word(values: list[int]) -> list[int]:
    values = list(values)
    while len(values) > WORD_BYTES and not any(values[-WORD_BYTES:]):
        values.pop()
    while not values or len(values) % WORD_BYTES or any(values[-WORD_BYTES:]):
        values.append(0)
    return values


def hex_to_mif(
    hex_file: str | Path,
    output_file: str | Path | None = None,
    width: int = 8,
    max_depth: int | None = None,
) -> str:
    if width not in (8, 32):
        raise ValueError("width must be 8 or 32")
    if max_depth is not None and max_depth <= 0:
        raise ValueError("max_depth must be a positive number of memory entries")

    hex_path = Path(hex_file)
    values = _with_single_halt_word(_read_bytes(hex_path))

    if width == 32:
        cells = [
            int.from_bytes(bytes(values[index : index + WORD_BYTES]), "little")
            for index in range(0, len(values), WORD_BYTES)
        ]
        title = "-- Memory Initialization File for CPU program (32-bit word-addressed)"
    else:
        cells = values
        title = "-- Memory Initialization File for CPU program"

    if max_depth is not None and len(cells) > max_depth:
        unit = "words" if width == 32 else "bytes"
        raise ValueError(
            f"Program plus required 4-byte halt word needs {len(cells)} {unit} "
            f"({len(values)} bytes), but target depth is {max_depth}; refusing to truncate"
        )

    depth = max_depth if max_depth is not None else len(cells)
    digits = width // 4
    mif_lines = [
        title,
        f"-- Generated from {hex_path.name}",
        "",
        f"WIDTH={width};",
        f"DEPTH={depth};",
        "",
        "ADDRESS_RADIX=DEC;",
        "DATA_RADIX=HEX;",
        "",
        "CONTENT BEGIN",
        f"\t[0..{depth - 1}] : {'0' * digits};",
        *(f"\t{index:<4}: {cell:0{digits}X};" for index, cell in enumerate(cells) if cell),
        "END;",
    ]

    result = "\n".join(mif_lines)
    destination = Path(output_file) if output_file is not None else hex_path.with_suffix(".mif")
    destination.write_text(result, encoding="ascii")

    logger.info("MIF file written to: %s", destination)
    if width == 32:
        logger.info(
            "Program size: %d bytes -> %d words -> DEPTH=%d", len(values), len(cells), depth
        )
    else:
        logger.info("Program size (trimmed): %d bytes -> DEPTH=%d", len(values), depth)
        if max_depth is not None:
            logger.info("Full RAM depth: %d (%d unused bytes)", max_depth, max_depth - len(cells))
    logger.info("Data width: %d bits", width)
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="[INFO] %(message)s")
    parser = argparse.ArgumentParser(description="Convert a hex image to Quartus .mif format")
    parser.add_argument("input", type=Path, help="Input hex file")
    parser.add_argument("output", type=Path, nargs="?", default=None, help="Output .mif file")
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Memory depth in entries (words for --width 32, bytes for --width 8); "
        "for the 32-bit instruction ROM pass 2^(RAM_ADDR_WIDTH-2).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=8,
        choices=[8, 32],
        help="8 (default, byte-addressed) or 32 (word-addressed, little-endian packing).",
    )
    args = parser.parse_args(argv)

    try:
        hex_to_mif(args.input, args.output, width=args.width, max_depth=args.depth)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
