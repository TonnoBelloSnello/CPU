import ast
from functools import lru_cache

from .constants import STACK_INSTRUCTIONS, decode_operation
from .constload import (
    constant_load_expression,
    constant_load_word_count,
    is_constant_load,
)
from .directives import DirectiveError, evaluate_expression
from .parser import split_instruction
from .reglist import is_register_list, register_list_length
from .text import text_expansion_word_count

MatrixLiteral = tuple[tuple[int, ...], ...]
MatrixTable = dict[str, MatrixLiteral]
MAX_MATRIX_DIMENSION = 15
MAX_MATRIX_ADDRESS = 0xFFF


def parse_matrix_literal(token: str) -> MatrixLiteral | None:
    return _parse_matrix_literal_cached(token.strip())


@lru_cache(maxsize=2048)
def _parse_matrix_literal_cached(token: str) -> MatrixLiteral | None:
    if not (token.startswith("{{") and token.endswith("}}")):
        return None

    converted = token.replace("{", "[").replace("}", "]")
    try:
        parsed = ast.literal_eval(converted)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Invalid matrix literal: {token}") from exc

    if not isinstance(parsed, list) or not parsed:
        raise ValueError(f"Matrix literal must be a non-empty 2D collection: {token}")

    if not isinstance(parsed[0], list):
        raise ValueError(f"Matrix literal must be a non-empty 2D collection: {token}")

    expected_cols = len(parsed[0])
    rows: list[tuple[int, ...]] = []
    for row in parsed:
        if not isinstance(row, list) or not row or len(row) != expected_cols:
            raise ValueError(f"Matrix rows must be non-empty and equal length: {token}")
        if any(type(v) is not int or v < 0 or v > 255 for v in row):
            raise ValueError(f"Matrix values must be integers in 0..255: {token}")
        rows.append(tuple(row))

    return tuple(rows)


def flatten_matrix(matrix: MatrixLiteral) -> list[int]:
    return [value for row in matrix for value in row]


@lru_cache(maxsize=2048)
def canonicalize_matrix(matrix: MatrixLiteral) -> str:
    row_parts = ["{" + ",".join(str(v) for v in row) + "}" for row in matrix]
    return "{" + ",".join(row_parts) + "}"


@lru_cache(maxsize=2048)
def canonicalize_matrix_token(token: str) -> str | None:
    matrix = parse_matrix_literal(token)
    return canonicalize_matrix(matrix) if matrix is not None else None


def get_matrix_symbol_key(token: str, symbol_table: dict[str, int]) -> str | None:
    token = token.strip()
    if not (token.startswith("{") and token.endswith("}")):
        return None
    key = canonicalize_matrix_token(token)
    return key if key is not None and key in symbol_table else None


def resolve_matrix_operand(token: str, matrix_table: MatrixTable | None) -> MatrixLiteral | None:
    if matrix_table is None:
        matrix_table = {}
    token = token.strip()
    parsed = parse_matrix_literal(token)
    if parsed is not None:
        return parsed
    if token in matrix_table:
        return matrix_table[token]
    canonical = canonicalize_matrix_token(token)
    if canonical is not None and canonical in matrix_table:
        return matrix_table[canonical]
    return None


def make_mmul_result_key(left_mx: MatrixLiteral, right_mx: MatrixLiteral) -> str:
    return f"mmul:{canonicalize_matrix(left_mx)}:{canonicalize_matrix(right_mx)}"


def validate_matrix_multiplication(
    left_mx: MatrixLiteral,
    right_mx: MatrixLiteral,
) -> tuple[int, int, int]:
    rows_a = len(left_mx)
    cols_a = len(left_mx[0])
    rows_b = len(right_mx)
    cols_b = len(right_mx[0])
    if any(
        dimension > MAX_MATRIX_DIMENSION
        for dimension in (rows_a, cols_a, rows_b, cols_b)
    ):
        raise ValueError(
            "Hardware MUL matrix dimensions must each be at most "
            f"{MAX_MATRIX_DIMENSION}: got {rows_a}x{cols_a} and {rows_b}x{cols_b}"
        )
    if cols_a != rows_b:
        raise ValueError(
            "Incompatible matrix dimensions for MUL: "
            f"{rows_a}x{cols_a} cannot be multiplied by {rows_b}x{cols_b}"
        )
    return rows_a, cols_a, cols_b


def is_matrix_operand(token: str, matrix_var_names: set[str]) -> bool:
    token = token.strip()
    if token.startswith("{{") and token.endswith("}}"):
        return True
    return token in matrix_var_names


def count_instruction_words(
    line: str,
    matrix_var_names: set[str],
    symbols: dict[str, int] | None = None,
) -> int:
    line = line.strip()
    if not line or line.endswith(":"):
        return 0

    operation, operands = split_instruction(line)
    decoded = decode_operation(operation)
    if decoded is None:
        return 1

    base_op = decoded[0]
    if base_op in STACK_INSTRUCTIONS and len(operands) == 1 and is_register_list(operands[0]):
        try:
            return register_list_length(operands[0])
        except ValueError:
            return 1

    if base_op == "mov" and len(operands) == 2 and is_constant_load(operands[1]):
        expression = constant_load_expression(operands[1])
        try:
            value = evaluate_expression(expression, symbols or {})
        except DirectiveError as exc:
            raise ValueError(
                f"{exc}; a '=' expression may only reference constants and "
                f"data symbols, not code labels: {line}"
            ) from exc
        return constant_load_word_count(value)

    if base_op == "mul" and len(operands) == 3:
        left = operands[1].strip()
        right = operands[2].strip()
        if is_matrix_operand(left, matrix_var_names) or is_matrix_operand(right, matrix_var_names):
            return 4

    if base_op == "text":
        try:
            return text_expansion_word_count(operation, operands)
        except ValueError:
            return 1

    return 1
