from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .assemble import assemble

OUT_DIR = Path(__file__).resolve().parent / "out"

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="[INFO] %(message)s")
    parser = argparse.ArgumentParser(description="Encode a .de1 source into a binary image")
    parser.add_argument("source", type=Path, help="Assembly source to encode")
    args = parser.parse_args(argv)

    source: Path = args.source
    output = OUT_DIR / source.with_suffix(".bin").name
    logger.info("Encoding %s into %s", source, output)

    try:
        lines = source.read_text(encoding="utf-8").splitlines()
        program = assemble(lines, source.resolve().parent)
        OUT_DIR.mkdir(exist_ok=True)
        output.write_bytes(program.to_bytes(halt_word=False))
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    logger.info("Successfully encoded %d instructions", len(program.words))
    logger.info("Binary output written to %s", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
