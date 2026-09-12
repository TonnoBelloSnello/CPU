from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def bin_to_hex_text(input_file: str | Path, output_file: str | Path) -> int:
    data = Path(input_file).read_bytes()
    Path(output_file).write_text("".join(f"{byte:02X}\n" for byte in data), encoding="ascii")
    return len(data)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="[INFO] %(message)s")
    parser = argparse.ArgumentParser(description="Convert a binary image to $readmemh hex text")
    parser.add_argument("input", type=Path, help="Input .bin file")
    parser.add_argument("output", type=Path, help="Output .hex file")
    args = parser.parse_args(argv)

    try:
        written = bin_to_hex_text(args.input, args.output)
    except OSError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    logger.info("Converted %d bytes from %s to %s", written, args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
