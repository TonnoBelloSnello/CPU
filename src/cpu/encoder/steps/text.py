from __future__ import annotations

import hashlib
from collections.abc import Container, Iterable, Iterator, Mapping
from dataclasses import dataclass

from .constants import CONDITION_SUFFIX_BY_CODE, REGISTER_ALIASES, decode_operation
from .parser import parse_string_literal, split_instruction, strip_comments

TEXT_X_TEMP_REG = 8
TEXT_Y_TEMP_REG = 9
TEXT_COLOR_REG = 12
TEXT_DEFAULT_COLOR = 255
TEXT_SOURCE_PTR_MAX = 0xFFF
TEXT_REG_MAX = 12
TEXT_SPILL_BYTES = 3  # covers every documented RAM_ADDR_WIDTH
TEXT_SPILL_SYMBOLS = {
    TEXT_X_TEMP_REG: "__text_spill_r8",
    TEXT_Y_TEMP_REG: "__text_spill_r9",
    TEXT_COLOR_REG: "__text_spill_r12",
}


@dataclass(frozen=True)
class TextInstruction:
    operation: str
    condition_suffix: str
    x_token: str
    y_token: str
    source_token: str
    color_token: str | None


@dataclass(frozen=True)
class TextExpansionMetadata:
    final_x_reg: int
    final_y_reg: int
    setup_lines: tuple[str, ...]
    teardown_lines: tuple[str, ...]

    @property
    def total_words(self) -> int:
        return len(self.setup_lines) + 1 + len(self.teardown_lines)


def mnemonic_with_condition(base: str, condition_suffix: str) -> str:
    return f"{base}{condition_suffix}".upper()


def parse_register_token(token: str) -> int | None:
    lowered = token.strip().lower()
    if lowered in REGISTER_ALIASES:
        return REGISTER_ALIASES[lowered]
    if lowered.startswith("r") and lowered[1:].isdigit():
        return int(lowered[1:])
    return None


def parse_v_immediate(token: str) -> int | None:
    stripped = token.strip()
    lowered = stripped.lower()
    if lowered.startswith("vb"):
        return int(stripped[2:], 2)
    if lowered.startswith("v"):
        return int(stripped[1:])
    return None


def text_blob_key(blob: bytes) -> str:
    digest = hashlib.sha1(blob).hexdigest()[:20]
    return f"__text_blob::{digest}"


def text_label_ref_key(label: str) -> str:
    return f"__text_ref_label::{label.strip()}"


def parse_text_instruction(operation: str, operands: list[str]) -> TextInstruction:
    decoded = decode_operation(operation)
    if decoded is None or decoded[0] != "text":
        raise ValueError(f"Not a TEXT instruction: {operation}")

    _, condition, flag, _, _ = decoded
    if flag:
        raise ValueError("TEXT does not support the S flag suffix")
    if len(operands) not in (3, 4):
        raise ValueError(
            f"TEXT expects 3 or 4 operands, got {len(operands)} ({operation} {' ,'.join(operands)})"
        )

    return TextInstruction(
        operation=operation,
        condition_suffix=CONDITION_SUFFIX_BY_CODE.get(condition, ""),
        x_token=operands[0].strip(),
        y_token=operands[1].strip(),
        source_token=operands[2].strip(),
        color_token=operands[3].strip() if len(operands) == 4 else None,
    )


def iter_text_instructions(instructions: Iterable[str]) -> Iterator[TextInstruction]:
    for raw_line in instructions:
        line = strip_comments(raw_line).strip()
        if not line or line.endswith(":"):
            continue
        operation, operands = split_instruction(line)
        decoded = decode_operation(operation)
        if decoded is None or decoded[0] != "text":
            continue
        yield parse_text_instruction(operation, operands)


def _materialize_operand(
    token: str,
    *,
    destination_reg: int,
    condition_suffix: str,
    operand_name: str,
    setup_lines: list[str],
) -> None:
    immediate_value = parse_v_immediate(token)
    if immediate_value is not None:
        setup_lines.append(
            f"{mnemonic_with_condition('MOV', condition_suffix)} "
            f"R{destination_reg}, V{immediate_value}"
        )
        return

    register_index = parse_register_token(token)
    if register_index is None:
        raise ValueError(
            f"TEXT {operand_name} must be a register R0..R12 or a V-prefixed "
            f"immediate, got: {token}"
        )
    if not 0 <= register_index <= TEXT_REG_MAX:
        raise ValueError(f"TEXT {operand_name} register must be R0..R12, got: {token}")

    if register_index in TEXT_SPILL_SYMBOLS:
        setup_lines.append(
            f"{mnemonic_with_condition('MOVM', condition_suffix)} "
            f"R{destination_reg}, [{TEXT_SPILL_SYMBOLS[register_index]}]"
        )
    elif register_index != destination_reg:
        setup_lines.append(
            f"{mnemonic_with_condition('MOV', condition_suffix)} "
            f"R{destination_reg}, R{register_index}"
        )


def build_text_expansion_metadata(text_instr: TextInstruction) -> TextExpansionMetadata:
    cond = text_instr.condition_suffix
    save_mnemonic = mnemonic_with_condition("SAVEM", cond)
    load_mnemonic = mnemonic_with_condition("MOVM", cond)
    setup_lines = [
        f"{save_mnemonic} R{reg}, [{TEXT_SPILL_SYMBOLS[reg]}]"
        for reg in (TEXT_X_TEMP_REG, TEXT_Y_TEMP_REG, TEXT_COLOR_REG)
    ]

    _materialize_operand(
        text_instr.x_token,
        destination_reg=TEXT_X_TEMP_REG,
        condition_suffix=cond,
        operand_name="X",
        setup_lines=setup_lines,
    )
    _materialize_operand(
        text_instr.y_token,
        destination_reg=TEXT_Y_TEMP_REG,
        condition_suffix=cond,
        operand_name="Y",
        setup_lines=setup_lines,
    )
    _materialize_operand(
        text_instr.color_token or f"V{TEXT_DEFAULT_COLOR}",
        destination_reg=TEXT_COLOR_REG,
        condition_suffix=cond,
        operand_name="color",
        setup_lines=setup_lines,
    )

    teardown_lines = tuple(
        f"{load_mnemonic} R{reg}, [{TEXT_SPILL_SYMBOLS[reg]}]"
        for reg in (TEXT_COLOR_REG, TEXT_Y_TEMP_REG, TEXT_X_TEMP_REG)
    )

    return TextExpansionMetadata(
        final_x_reg=TEXT_X_TEMP_REG,
        final_y_reg=TEXT_Y_TEMP_REG,
        setup_lines=tuple(setup_lines),
        teardown_lines=teardown_lines,
    )


def text_source_blob_from_token(
    source_token: str,
    *,
    space_string_values: Mapping[str, bytes],
    known_symbols: Container[str],
) -> tuple[bytes, str | None]:
    literal_value = parse_string_literal(source_token)
    if literal_value is not None:
        return literal_value.encode("utf-8") + b"\x00", None

    label = source_token.strip()
    if label in space_string_values:
        return space_string_values[label] + b"\x00", text_label_ref_key(label)
    if label in known_symbols:
        raise ValueError(f"TEXT source '{label}' is defined but is not a string variable")
    raise ValueError(f"Undefined TEXT source label: {label}")


def resolve_text_source_address(source_token: str, symbol_table: Mapping[str, int]) -> int:
    literal_value = parse_string_literal(source_token)
    if literal_value is not None:
        blob = literal_value.encode("utf-8") + b"\x00"
        key = text_blob_key(blob)
    else:
        label = source_token.strip()
        key = text_label_ref_key(label)
        if key not in symbol_table and label in symbol_table:
            raise ValueError(f"TEXT source '{label}' is defined but is not a string variable")

    if key not in symbol_table:
        raise ValueError(f"Unresolved TEXT source: {source_token}")

    address = symbol_table[key]
    if not (0 <= address <= TEXT_SOURCE_PTR_MAX):
        raise ValueError(
            f"TEXT source address out of 12-bit immediate range (0..{TEXT_SOURCE_PTR_MAX}): "
            f"{source_token} -> {address}"
        )
    return address


def text_expansion_word_count(operation: str, operands: list[str]) -> int:
    return build_text_expansion_metadata(parse_text_instruction(operation, operands)).total_words
