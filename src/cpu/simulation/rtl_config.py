from __future__ import annotations

import re
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
HDL_DIR: Final = PROJECT_ROOT / "hdl"
CPU_PKG_PATH: Final = HDL_DIR / "cpu_pkg.sv"

try:
    CPU_PKG_TEXT: Final = CPU_PKG_PATH.read_text(encoding="utf-8")
except OSError as exc:
    raise RuntimeError(
        f"Cannot read canonical RTL configuration {CPU_PKG_PATH}: {exc}"
    ) from exc


def cpu_pkg_int(name: str) -> int:
    matches = re.findall(
        rf"^\s*localparam\s+int\s+{re.escape(name)}\s*=\s*([0-9][0-9_]*)\s*;",
        CPU_PKG_TEXT,
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one literal integer localparam {name} in {CPU_PKG_PATH}, "
            f"found {len(matches)}"
        )
    return int(matches[0].replace("_", ""))


RAM_ADDR_WIDTH: Final = cpu_pkg_int("RAM_ADDR_WIDTH")
VGA_FB_WIDTH: Final = cpu_pkg_int("VGA_FB_WIDTH")
VGA_FB_HEIGHT: Final = cpu_pkg_int("VGA_FB_HEIGHT")
MMIO_WINDOW_BYTES: Final = cpu_pkg_int("MMIO_WINDOW_BYTES")
NPU_ACC_WIDTH: Final = cpu_pkg_int("NPU_ACC_WIDTH")
LOADER_MAX_PROGRAM_SIZE: Final = cpu_pkg_int("LOADER_MAX_PROGRAM_SIZE")
