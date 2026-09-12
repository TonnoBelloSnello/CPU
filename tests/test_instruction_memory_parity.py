from __future__ import annotations

import shutil

import pytest

from src.cpu.simulation.runner import run_snapshot


@pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not available on PATH",
)
def test_runtime_data_store_cannot_modify_a_later_instruction() -> None:
    result = run_snapshot(
        """
        main:
            MOV R0, V0
            SAVEM R0, [victim]
            B victim
            MOV R1, V1
        victim:
            MOV R7, V77
        """,
        mem_start=0,
        mem_end=64,
        max_cycles=5_000,
    )

    victim = result["labels"]["victim"]
    memory = {cell["addr"]: cell["dec"] for cell in result["memory"]}
    assert [memory[victim + offset] for offset in range(4)] == [0x00, 0x00, 0xA0, 0xE3]
    assert result["registers"]["R7"] == {"dec": 77, "hex": "004D"}
