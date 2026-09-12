from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .constants import (
    BINARY_IMMEDIATE_RE,
    DECIMAL_IMMEDIATE_RE,
    FP_INSTRUCTIONS,
    REGISTER_ALIAS_NAMES,
    REGISTER_TOKEN_RE,
    decode_operation,
)
from .directives import evaluate_expression
from .fp16 import fp16_literal_info, looks_like_fp_literal
from .matrix import (
    MatrixLiteral,
    MatrixTable,
    canonicalize_matrix,
    flatten_matrix,
    make_mmul_result_key,
    parse_matrix_literal,
    resolve_matrix_operand,
    validate_matrix_multiplication,
)
from .npu import is_npu_register_token
from .parser import parse_string_literal, split_instruction, strip_brackets, strip_comments
from .text import (
    TEXT_SPILL_BYTES,
    TEXT_SPILL_SYMBOLS,
    iter_text_instructions,
    text_blob_key,
    text_source_blob_from_token,
)

logger = logging.getLogger(__name__)

_SYMBOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTERNAL_SYMBOL_PREFIXES = ("__", "mmul:")
_NAME_SYNTAX_HINT = "expected a letter or underscore followed by letters, digits, or underscores"


class DataError(ValueError):
    def __init__(self, message: str, code: str, token: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.token = token
        self.index = -1


ErrorSink = Callable[[DataError], None]


@dataclass(slots=True)
class DataSection:
    symbols: dict[str, int] = field(default_factory=dict)
    memory: dict[int, int] = field(default_factory=dict)
    matrices: MatrixTable = field(default_factory=dict)
    strings: dict[str, bytes] = field(default_factory=dict)
    size: int = 0

    @property
    def matrix_names(self) -> set[str]:
        return {name for name in self.matrices if not name.startswith("{")}

    def place(self, name: str, values: Sequence[int], detail: str = "") -> None:
        logger.info("'%s' at address %d, %d byte(s)%s", name, self.size, len(values), detail)
        self.symbols[name] = self.size
        for offset, value in enumerate(values):
            self.memory[self.size + offset] = value
        self.size += len(values)

    def reserve(self, name: str, size: int) -> None:
        logger.info("'%s' at address %d, %d byte(s) reserved", name, self.size, size)
        self.symbols[name] = self.size
        self.size += size

    def place_named_matrix(self, name: str, matrix: MatrixLiteral) -> None:
        self.matrices[name] = matrix
        canonical = canonicalize_matrix(matrix)
        self.matrices[canonical] = matrix
        self.symbols.setdefault(canonical, self.size)
        self.place(name, flatten_matrix(matrix), f", matrix {len(matrix)}x{len(matrix[0])}")

    def place_matrix_literal(self, matrix: MatrixLiteral) -> None:
        key = canonicalize_matrix(matrix)
        self.matrices[key] = matrix
        if key not in self.symbols:
            self.place(key, flatten_matrix(matrix))


def _is_reserved_operand_symbol(name: str) -> bool:
    return (
        name.upper() in REGISTER_ALIAS_NAMES
        or is_npu_register_token(name)
        or REGISTER_TOKEN_RE.fullmatch(name) is not None
        or DECIMAL_IMMEDIATE_RE.fullmatch(name) is not None
        or BINARY_IMMEDIATE_RE.fullmatch(name) is not None
        or fp16_literal_info(name) is not None
    )


def validate_code_label(label_name: str) -> None:
    if _SYMBOL_NAME_RE.fullmatch(label_name) is None:
        raise ValueError(f"Invalid code label '{label_name}'; {_NAME_SYNTAX_HINT}")
    if label_name.startswith("__"):
        raise ValueError(f"Code label '{label_name}' uses the reserved internal namespace '__'")
    if _is_reserved_operand_symbol(label_name):
        raise ValueError(f"Code label '{label_name}' collides with a reserved operand token")


def _validate_new_symbol(name: str, symbols: Mapping[str, int]) -> None:
    if not name:
        raise DataError("Data declaration is missing a variable name", "space-name")
    if name.startswith(_INTERNAL_SYMBOL_PREFIXES):
        raise DataError(
            f"Variable name '{name}' uses a reserved internal namespace", "space-name", name
        )
    if _SYMBOL_NAME_RE.fullmatch(name) is None:
        raise DataError(f"Invalid variable name '{name}'; {_NAME_SYNTAX_HINT}", "space-name", name)
    if _is_reserved_operand_symbol(name):
        raise DataError(
            f"Variable name '{name}' collides with a reserved operand token", "space-name", name
        )
    if name in symbols:
        raise DataError(f"Duplicate data declaration: '{name}'", "space-name", name)


def _binary_bytes(name: str, value: str) -> list[int]:
    bits = value.replace(" ", "")
    if not bits:
        raise DataError(f"Variable '{name}' has no value", "space-value", name)
    if any(ch not in "01" for ch in bits):
        raise DataError(
            f"Variable '{name}' has invalid binary value '{value}'", "space-binary", value
        )
    padded = bits.zfill((len(bits) + 7) // 8 * 8)
    return [int(padded[offset : offset + 8], 2) for offset in range(0, len(padded), 8)]


def _place_assignment(section: DataSection, name: str, value: str) -> None:
    string_value = parse_string_literal(value)
    if string_value is not None:
        encoded = string_value.encode("utf-8")
        if not encoded:
            raise DataError(f"Variable '{name}' has empty string value", "space-string", name)
        section.strings[name] = encoded
        section.place(name, encoded)
        return

    try:
        matrix = parse_matrix_literal(value)
    except ValueError as exc:
        raise DataError(str(exc), "space-matrix", value) from exc
    if matrix is not None:
        section.place_named_matrix(name, matrix)
        return

    literal = fp16_literal_info(value)
    if literal is not None:
        bits = literal[1]
        section.place(name, (bits & 0xFFFF).to_bytes(2, "little"), f", float16 (0x{bits:04X})")
        return
    if looks_like_fp_literal(value):
        raise DataError(f"Invalid FP literal: {value}", "space-fp-literal", value)

    section.place(name, _binary_bytes(name, value))


def _place_reservation(
    section: DataSection, name: str, size_text: str, constants: Mapping[str, int]
) -> None:
    try:
        size = evaluate_expression(size_text, dict(constants))
        if size < 0:
            raise ValueError("size must be non-negative")
    except ValueError as exc:
        raise DataError(
            f"Invalid size '{size_text}' for variable '{name}': {exc}",
            "space-size",
            size_text or name,
        ) from exc
    section.reserve(name, size)


def _place_declaration(section: DataSection, line: str, constants: Mapping[str, int]) -> None:
    separator = "=" if "=" in line else ":" if ":" in line else None
    if separator is None:
        raise DataError(f"Invalid data declaration: {line}", "space-declaration")
    name, value = (part.strip() for part in line.split(separator, 1))
    _validate_new_symbol(name, section.symbols)
    if separator == "=":
        _place_assignment(section, name, value)
    else:
        _place_reservation(section, name, value, constants)


def parse_space_section(
    lines: Sequence[str],
    constants: Mapping[str, int] | None = None,
    *,
    on_error: ErrorSink | None = None,
) -> DataSection:
    section = DataSection()
    for index, raw_line in enumerate(lines):
        line = strip_comments(raw_line.strip())
        if not line or line.lower() in {"space:", "main:"}:
            continue
        try:
            _place_declaration(section, line, constants or {})
        except DataError as exc:
            if on_error is None:
                raise
            exc.index = index
            on_error(exc)
    return section


def _report(exc: ValueError, code: str, on_error: ErrorSink | None) -> None:
    if on_error is None:
        raise exc
    on_error(exc if isinstance(exc, DataError) else DataError(str(exc), code))


def _place_inline_matrices(section: DataSection, operation: str, operands: list[str]) -> None:
    for operand in operands:
        matrix = parse_matrix_literal(strip_brackets(operand))
        if matrix is not None:
            section.place_matrix_literal(matrix)

    decoded = decode_operation(operation)
    if decoded is None or decoded[0] != "mul" or len(operands) != 3:
        return
    left = resolve_matrix_operand(operands[1], section.matrices)
    right = resolve_matrix_operand(operands[2], section.matrices)
    if left is None and right is None:
        return
    if left is None or right is None:
        raise DataError(
            "MUL matrix mode requires two matrix operands, got "
            f"'{operands[1]}' and '{operands[2]}'",
            "matrix",
        )
    rows, _, cols = validate_matrix_multiplication(left, right)
    result_key = make_mmul_result_key(left, right)
    if result_key not in section.symbols:
        section.place(result_key, bytes(rows * cols))


def _place_inline_fp_literals(section: DataSection, operation: str, operands: list[str]) -> None:
    decoded = decode_operation(operation)
    if decoded is None or decoded[0] not in FP_INSTRUCTIONS:
        return
    for token in operands:
        literal = fp16_literal_info(token)
        if literal is None:
            continue
        key, bits = literal
        if key not in section.symbols:
            section.place(key, (bits & 0xFFFF).to_bytes(2, "little"))


def _place_text_blobs(
    section: DataSection, lines: Iterable[str], on_error: ErrorSink | None
) -> None:
    known_symbols = set(section.symbols)
    saw_text = False

    for line in lines:
        try:
            for text_instr in iter_text_instructions([line]):
                saw_text = True
                blob, label_ref_key = text_source_blob_from_token(
                    text_instr.source_token,
                    space_string_values=section.strings,
                    known_symbols=known_symbols,
                )
                blob_key = text_blob_key(blob)
                if blob_key not in section.symbols:
                    section.place(blob_key, blob)
                if label_ref_key is not None:
                    section.symbols[label_ref_key] = section.symbols[blob_key]
        except ValueError as exc:
            _report(exc, "text", on_error)

    if saw_text:
        for spill_symbol in TEXT_SPILL_SYMBOLS.values():
            section.place(spill_symbol, bytes(TEXT_SPILL_BYTES))


def _run_instruction_pass(
    section: DataSection,
    lines: Iterable[str],
    place: Callable[[DataSection, str, list[str]], None],
    on_error: ErrorSink | None,
) -> None:
    for raw_line in lines:
        line = strip_comments(raw_line).strip()
        if not line or line.endswith(":"):
            continue
        try:
            place(section, *split_instruction(line))
        except ValueError as exc:
            _report(exc, "instruction", on_error)


def prepare_data_section(
    space_lines: Sequence[str],
    instruction_lines: Sequence[str],
    constants: Mapping[str, int] | None = None,
    *,
    on_error: ErrorSink | None = None,
) -> DataSection:
    section = parse_space_section(space_lines, constants, on_error=on_error)
    _place_text_blobs(section, instruction_lines, on_error)
    _run_instruction_pass(section, instruction_lines, _place_inline_matrices, on_error)
    _run_instruction_pass(section, instruction_lines, _place_inline_fp_literals, on_error)
    return section
