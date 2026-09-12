from __future__ import annotations

import re

from .snapshot import MemoryCell, RegisterValue
from .templates import (
    MEMORY_END,
    MEMORY_START,
    REGISTER_END,
    REGISTER_START,
    VGA_END,
    VGA_START,
)

_AddressEntries = list[MemoryCell] | dict[int, MemoryCell]

REG_RE = re.compile(r"^(R\d+|Q\d+|A\d+|PC|LE|HEX)=(-?\d+)\s+\(0x([0-9a-fA-F]+)\)")
REG_UNKNOWN_RE = re.compile(
    r"^(R\d+|Q\d+|A\d+|PC|LE|HEX)=[XxZz]+(?:\s+\(0x[0-9a-fA-FxXzZ]+\))?$"
)
WIDE_REGISTER_HEX_WIDTH = {"Q": 16, "A": 8}
CPSR_RE = re.compile(r"^CPSR=0x([0-9a-fA-FxXzZ]+)")
CPSR_UNKNOWN_RE = re.compile(r"^CPSR=[XxZz]+$")
MEM_RE = re.compile(r"^M\[(\d+)\]=(-?\d+)\s+\(0x([0-9a-fA-F]+)\)")
MEM_UNKNOWN_RE = re.compile(r"^M\[(\d+)\]=([XxZz]+)")
VGA_RE = re.compile(r"^VGA\[(\d+)\]=(-?\d+)\s+\(0x([0-9a-fA-F]+)\)")
VGA_UNKNOWN_RE = re.compile(r"^VGA\[(\d+)\]=([XxZz]+)")

_SECTION_STARTS = {
    REGISTER_START: "registers",
    MEMORY_START: "memory",
    VGA_START: "vga",
}
_SECTION_ENDS = {
    REGISTER_END: "registers",
    MEMORY_END: "memory",
    VGA_END: "vga",
}


def _parse_address_entry(
    line: str,
    value_pattern: re.Pattern[str],
    unknown_pattern: re.Pattern[str],
    hex_width: int,
) -> MemoryCell | None:
    if match := value_pattern.match(line):
        addr_str, dec_str, hex_str = match.groups()
        return {
            "addr": int(addr_str),
            "dec": int(dec_str),
            "hex": hex_str.upper().zfill(hex_width),
        }
    if match := unknown_pattern.match(line):
        return {"addr": int(match.group(1)), "dec": None, "hex": None}
    return None


class SnapshotParser:
    def __init__(
        self, addr_width: int, data_width: int, *, latest_sections: bool = False
    ) -> None:
        self._reg_hex_width = (addr_width + 3) // 4
        self._mem_hex_width = (data_width + 3) // 4
        self._latest_sections = latest_sections
        self._section: str | None = None
        self.registers: dict[str, RegisterValue] = {}
        self._memory: _AddressEntries = {} if latest_sections else []
        self._framebuffer: _AddressEntries = {} if latest_sections else []

    @staticmethod
    def _entries(values: _AddressEntries) -> list[MemoryCell]:
        if isinstance(values, dict):
            return [values[addr] for addr in sorted(values)]
        return values

    @property
    def memory(self) -> list[MemoryCell]:
        return self._entries(self._memory)

    @property
    def framebuffer(self) -> list[MemoryCell]:
        return self._entries(self._framebuffer)

    def _start_section(self, section: str) -> None:
        self._section = section
        if not self._latest_sections:
            return
        if section == "registers":
            self.registers.clear()
        elif section == "memory":
            self._memory.clear()
        else:
            self._framebuffer.clear()

    @staticmethod
    def _store(entries: _AddressEntries, entry: MemoryCell) -> None:
        if isinstance(entries, dict):
            entries[entry["addr"]] = entry
        else:
            entries.append(entry)

    def _feed_register_line(self, line: str) -> bool:
        if match := REG_RE.match(line):
            name, dec_str, hex_str = match.groups()
            width = WIDE_REGISTER_HEX_WIDTH.get(name[0], self._reg_hex_width)
            self.registers[name] = {
                "dec": int(dec_str),
                "hex": hex_str.upper().zfill(width),
            }
            return True
        if match := REG_UNKNOWN_RE.match(line):
            self.registers[match.group(1)] = {"dec": None, "hex": None}
            return True
        if match := CPSR_RE.match(line):
            hex_value = match.group(1).upper()
            known = all(ch in "0123456789ABCDEF" for ch in hex_value)
            self.registers["CPSR"] = {"dec": None, "hex": hex_value if known else None}
            return True
        if CPSR_UNKNOWN_RE.match(line):
            self.registers["CPSR"] = {"dec": None, "hex": None}
            return True
        return False

    def feed_line(self, raw_line: str) -> str | None:
        line = raw_line.strip()
        if not line:
            return None

        if section := _SECTION_STARTS.get(line):
            self._start_section(section)
            return None
        if section := _SECTION_ENDS.get(line):
            if self._section == section:
                self._section = None
            return None

        if self._section == "registers":
            if self._feed_register_line(line):
                return None
        elif self._section == "memory":
            entry = _parse_address_entry(line, MEM_RE, MEM_UNKNOWN_RE, self._mem_hex_width)
            if entry is not None:
                self._store(self._memory, entry)
                return None
        elif self._section == "vga":
            entry = _parse_address_entry(line, VGA_RE, VGA_UNKNOWN_RE, self._mem_hex_width)
            if entry is not None:
                self._store(self._framebuffer, entry)
                return None

        return line


def parse_snapshot_output(
    output: str,
    addr_width: int,
    data_width: int,
) -> tuple[dict[str, RegisterValue], list[MemoryCell], list[MemoryCell], str]:
    parser = SnapshotParser(addr_width, data_width)
    log_lines = [
        raw_line for raw_line in output.splitlines() if parser.feed_line(raw_line) is not None
    ]
    return parser.registers, parser.memory, parser.framebuffer, "\n".join(log_lines).strip()
