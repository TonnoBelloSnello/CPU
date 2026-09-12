from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .steps.directives import is_directive_line, preprocess
from .steps.encoder import encode_asm, encode_bootstrap_jump
from .steps.matrix import count_instruction_words
from .steps.memory import DataError, DataSection, prepare_data_section, validate_code_label
from .steps.npu import NPU_BUILTIN_CONSTANTS
from .steps.parser import strip_comments
from .steps.prettify import normalize_arm_instructions

BOOTSTRAP_BYTES = 4
WORD_BYTES = 4
HALT_WORD = b"\x00\x00\x00\x00"


@dataclass(frozen=True, slots=True)
class SourceEntry:
    line: int
    raw: str
    stripped: str
    kind: Literal["section", "data", "label", "instruction"]

    @property
    def label(self) -> str:
        return self.stripped[:-1].strip()


class SourceError(ValueError):
    def __init__(
        self, entry: SourceEntry, message: str, code: str, token: str | None = None
    ) -> None:
        super().__init__(message)
        self.entry = entry
        self.code = code
        self.token = token


@dataclass(slots=True)
class ProgramLayout:
    entries: list[SourceEntry]
    data: DataSection
    symbols: dict[str, int]
    code_base: int
    entry_address: int
    expected_words: int


@dataclass(frozen=True, slots=True)
class AssembledProgram:
    code_base: int
    entry_address: int
    words: list[int]
    memory_init: dict[int, int]
    symbols: dict[str, int]

    def to_bytes(self, *, halt_word: bool = True) -> bytes:
        image = bytearray(encode_bootstrap_jump(self.entry_address).to_bytes(WORD_BYTES, "little"))
        image += bytes(
            self.memory_init.get(address, 0) for address in range(BOOTSTRAP_BYTES, self.code_base)
        )
        for word in self.words:
            image += word.to_bytes(WORD_BYTES, "little")
        if halt_word:
            image += HALT_WORD
        return bytes(image)


def _source_entries(lines: Sequence[str]) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    in_space = False
    for line_no, raw in enumerate(lines):
        stripped = strip_comments(raw).strip()
        if not stripped or is_directive_line(stripped):
            continue
        kind: Literal["section", "data", "label", "instruction"]
        if stripped.casefold() == "space:":
            kind = "section"
            in_space = True
        elif stripped.endswith(":"):
            kind = "label"
            in_space = False
        else:
            kind = "data" if in_space else "instruction"
        entries.append(SourceEntry(line_no, raw, stripped, kind))
    return entries


def layout_source(
    lines: Sequence[str],
    constants: dict[str, int],
    *,
    on_error: Callable[[SourceError], None] | None = None,
    require_instructions: bool = True,
) -> ProgramLayout:
    entries = _source_entries(lines)

    def report(entry: SourceEntry, message: str, code: str, token: str | None = None) -> None:
        error = SourceError(entry, message, code, token)
        if on_error is None:
            raise error
        on_error(error)

    saw_space = saw_code = False
    for entry in entries:
        if entry.kind == "section":
            if saw_space:
                report(entry, "Duplicate space: section.", "section", "space")
            if saw_code:
                report(entry, "space: must precede executable code.", "section", "space")
            saw_space = True
        elif entry.kind in {"label", "instruction"}:
            saw_code = True

    data_entries = [entry for entry in entries if entry.kind == "data"]
    instructions = [entry.stripped for entry in entries if entry.kind == "instruction"]

    def report_data(error: DataError) -> None:
        if 0 <= error.index < len(data_entries):
            report(data_entries[error.index], str(error), error.code, error.token)

    section = prepare_data_section(
        [entry.raw for entry in data_entries],
        instructions,
        constants,
        on_error=report_data if on_error is not None else None,
    )
    code_base = (section.size + WORD_BYTES - 1) // WORD_BYTES * WORD_BYTES + BOOTSTRAP_BYTES
    data_symbols = {name: addr + BOOTSTRAP_BYTES for name, addr in section.symbols.items()}
    early_symbols = {**constants, **data_symbols}
    symbols = dict(early_symbols)
    labels: set[str] = set()
    main: SourceEntry | None = None
    address = code_base

    for entry in entries:
        if entry.kind == "data":
            separator = "=" if "=" in entry.stripped else ":"
            name = entry.stripped.split(separator, 1)[0].strip()
            if name in constants:
                report(entry, f"constant/symbol collision: '{name}'", "space-name", name)
        elif entry.kind == "label":
            label = entry.label
            try:
                validate_code_label(label)
            except ValueError as exc:
                report(entry, str(exc), "label", label)
            if label in labels:
                report(entry, f"Duplicate code label '{label}'.", "label", label)
            elif label.casefold() == "main" and main is not None:
                report(entry, "Duplicate code label 'main'.", "label", label)
            if label in data_symbols:
                report(
                    entry,
                    f"data/code symbol collision: '{label}' is defined as both data "
                    "and a code label.",
                    "label",
                    label,
                )
            if label in constants:
                report(entry, f"constant/symbol collision: '{label}'", "label", label)
            labels.add(label)
            symbols.setdefault(label, address)
            if label.casefold() == "main" and main is None:
                main = entry
        elif entry.kind == "instruction":
            try:
                words = count_instruction_words(entry.stripped, section.matrix_names, early_symbols)
            except ValueError as exc:
                report(entry, str(exc), "instruction")
                words = 1
            address += WORD_BYTES * max(words, 1)

    anchor = main or next(
        (entry for entry in entries if entry.kind in {"label", "instruction"}),
        entries[0] if entries else SourceEntry(0, lines[0] if lines else "", "", "instruction"),
    )
    entry_address = symbols[main.label] if main is not None else code_base
    try:
        encode_bootstrap_jump(entry_address)
    except ValueError as exc:
        report(anchor, str(exc), "entry-address", main.label if main is not None else None)
    if require_instructions and not instructions:
        report(
            anchor, "Program contains no instructions; no instructions encoded.", "no-instructions"
        )
    return ProgramLayout(
        entries, section, symbols, code_base, entry_address, (address - code_base) // WORD_BYTES
    )


def assemble(
    lines: Sequence[str],
    base_dir: Path | None = None,
    *,
    require_instructions: bool = True,
) -> AssembledProgram:
    source, constants = preprocess(list(lines), base_dir)
    layout = layout_source(source, constants, require_instructions=require_instructions)
    instructions = [entry.stripped for entry in layout.entries if entry.kind == "instruction"]
    words = encode_asm(
        normalize_arm_instructions(instructions), layout.symbols, layout.data.matrices
    )
    if len(words) != layout.expected_words:
        raise ValueError(
            f"encoder produced a partial program ({len(words)} of {layout.expected_words} "
            "instruction words)"
        )
    return AssembledProgram(
        code_base=layout.code_base,
        entry_address=layout.entry_address,
        words=words,
        memory_init={addr + BOOTSTRAP_BYTES: value for addr, value in layout.data.memory.items()},
        symbols={
            name: value
            for name, value in layout.symbols.items()
            if name not in NPU_BUILTIN_CONSTANTS
        },
    )
