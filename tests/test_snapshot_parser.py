from src.cpu.simulation.parser import parse_snapshot_output
from src.cpu.simulation.templates import (
    MEMORY_END,
    MEMORY_START,
    REGISTER_END,
    REGISTER_START,
    VGA_END,
    VGA_START,
)


def test_parse_snapshot_output_includes_vga_framebuffer() -> None:
    output = "\n".join(
        [
            "PIXEL: x=1 y=2 color=255 addr=129",
            REGISTER_START,
            "R0=5 (0x5)",
            "PC=12 (0xc)",
            "LE=3 (0x3)",
            "HEX=255 (0xff)",
            "CPSR=0x60000000",
            REGISTER_END,
            MEMORY_START,
            "M[0]=1 (0x1)",
            "M[1]=X",
            MEMORY_END,
            VGA_START,
            "VGA[0]=255 (0xff)",
            "VGA[1]=0 (0x0)",
            "VGA[2]=X",
            VGA_END,
            "Halt: Encountered null instruction",
        ]
    )

    registers, memory, framebuffer, log = parse_snapshot_output(output, addr_width=16, data_width=8)

    assert registers["R0"] == {"dec": 5, "hex": "0005"}
    assert registers["PC"] == {"dec": 12, "hex": "000C"}
    assert registers["HEX"] == {"dec": 255, "hex": "00FF"}
    assert registers["CPSR"] == {"dec": None, "hex": "60000000"}

    assert memory == [
        {"addr": 0, "dec": 1, "hex": "01"},
        {"addr": 1, "dec": None, "hex": None},
    ]
    assert framebuffer == [
        {"addr": 0, "dec": 255, "hex": "FF"},
        {"addr": 1, "dec": 0, "hex": "00"},
        {"addr": 2, "dec": None, "hex": None},
    ]

    assert "PIXEL: x=1 y=2 color=255 addr=129" in log
    assert "Halt: Encountered null instruction" in log
