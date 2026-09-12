import pytest
from conftest import run_simulation

from src.cpu.simulation.runner import run_snapshot


@pytest.mark.parametrize(
    ("instructions", "expected_log"),
    [
        (
            ["MOV R0, V10", "MOV R1, V20", "PIXEL R0, R1, V255"],
            "PIXEL: x=10 y=20 color=255 addr=3210",
        ),
        (
            ["MOV R0, V5", "MOV R1, V3", "MOV R2, V128", "PIXEL R0, R1, R2"],
            "PIXEL: x=5 y=3 color=128 addr=485",
        ),
        (
            ["MOV R0, V0", "MOV R1, V0", "PIXEL R0, R1, V42"],
            "PIXEL: x=0 y=0 color=42 addr=0",
        ),
        (
            ["MOV R0, V159", "MOV R1, V119", "PIXEL R0, R1, V200"],
            "PIXEL: x=159 y=119 color=200 addr=19199",
        ),
    ],
    ids=["immediate-color", "register-color", "origin", "max-coordinates"],
)
def test_pixel_simple_write(instructions: list[str], expected_log: str) -> None:
    output, _ = run_simulation(["main:", *instructions])

    assert expected_log in output


def test_pixel_conditional() -> None:
    program = [
        "main:",
        "MOV R0, V10",
        "MOV R1, V10",
        "CMP R0, R1",
        "MOV R2, V5",
        "MOV R3, V5",
        "PIXELEQ R2, R3, V100",
        "MOV R4, V20",
        "PIXELNE R2, R3, V50",
    ]

    output, _ = run_simulation(program)

    assert "PIXEL: x=5 y=5 color=100 addr=805" in output
    assert "Condition not met" in output


def test_pixel_multiple_writes() -> None:
    program = [
        "main:",
        "MOV R0, V0",
        "MOV R1, V0",
        "PIXEL R0, R1, V255",

        "MOV R0, V32",
        "MOV R1, V24",
        "PIXEL R0, R1, V128",

        "MOV R0, V159",
        "MOV R1, V119",
        "PIXEL R0, R1, V1",
    ]

    output, _ = run_simulation(program)

    assert "PIXEL: x=0 y=0 color=255 addr=0" in output
    assert "PIXEL: x=32 y=24 color=128 addr=3872" in output
    assert "PIXEL: x=159 y=119 color=1 addr=19199" in output


def test_pixel_in_loop() -> None:
    program = [
        "main:",
        "MOV R0, V0",
        "MOV R1, V10",
        "draw_loop:",
        "PIXEL R0, R1, V255",
        "ADD R0, R0, V1",
        "CMP R0, V4",
        "BLT draw_loop",
    ]

    output, _ = run_simulation(program)

    assert "PIXEL: x=0 y=10 color=255 addr=1600" in output
    assert "PIXEL: x=1 y=10 color=255 addr=1601" in output
    assert "PIXEL: x=2 y=10 color=255 addr=1602" in output
    assert "PIXEL: x=3 y=10 color=255 addr=1603" in output


def test_pixelnb_basic_immediate_color() -> None:
    program = [
        "main:",
        "MOV R0, V10",
        "MOV R1, V20",
        "PIXELNB R0, R1, V255",
    ]

    output, _ = run_simulation(program)

    assert "PIXEL: x=10 y=20 color=255 addr=3210" in output


def test_pixelnb_conditional() -> None:
    program = [
        "main:",
        "MOV R0, V1",
        "CMP R0, V1",
        "MOV R2, V5",
        "MOV R3, V6",
        "PIXELNBEQ R2, R3, V77",
        "PIXELNBNE R2, R3, V99",
    ]

    output, _ = run_simulation(program)

    assert "PIXEL: x=5 y=6 color=77 addr=965" in output
    assert "color=99" not in output


def test_pixelnb_out_of_bounds_clipped() -> None:
    program = "\n".join(
        [
            "main:",
            "MOV R0, V200",
            "MOV R1, V130",
            "PIXELNB R0, R1, V255",
        ]
    )

    snapshot = run_snapshot(program_text=program, mem_start=0, mem_end=8)
    framebuffer = snapshot["framebuffer"]
    log = str(snapshot["log"])

    assert framebuffer == []
    assert "PIXEL:" not in log


def test_pixelnb_then_pixel_preserves_write_order() -> None:
    program = "\n".join(
        [
            "main:",
            "MOV R0, V4",
            "MOV R1, V6",
            "PIXELNB R0, R1, V10",
            "PIXEL R0, R1, V20",
        ]
    )

    snapshot = run_snapshot(program_text=program, mem_start=0, mem_end=8)
    framebuffer_entries = snapshot["framebuffer"]
    log = str(snapshot["log"])

    assert framebuffer_entries == [{"addr": 964, "dec": 20, "hex": "14"}]
    assert "PIXEL: x=4 y=6 color=10 addr=964" in log
    assert "PIXEL: x=4 y=6 color=20 addr=964" in log
    assert log.index("color=10 addr=964") < log.index("color=20 addr=964")
