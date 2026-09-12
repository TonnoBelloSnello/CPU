import logging
import re
from typing import NamedTuple

from .constants import (
    BR_CLASS_INSTRUCTIONS,
    COMPARE_INSTRUCTIONS,
    CONTROL_FLOW_BRANCH_INSTRUCTIONS,
    DEFAULT_CONDITION,
    EXT_CLASS_INSTRUCTIONS,
    FP_INSTRUCTIONS,
    MAX_BRANCH_TARGET,
    MEM_CLASS_INSTRUCTIONS,
    MEMORY_ACCESS_INSTRUCTIONS,
    MEMORY_OPERAND_INSTRUCTIONS,
    REGISTER_ALIASES,
    SHIFT_PSEUDO_INSTRUCTIONS,
    STACK_INSTRUCTIONS,
    decode_operation,
)
from .constload import (
    constant_load_expression,
    expand_constant_load,
    is_constant_load,
)
from .directives import evaluate_expression
from .fp16 import fp16_literal_info, looks_like_fp_literal
from .matrix import (
    MAX_MATRIX_ADDRESS,
    MatrixLiteral,
    MatrixTable,
    canonicalize_matrix,
    get_matrix_symbol_key,
    make_mmul_result_key,
    resolve_matrix_operand,
    validate_matrix_multiplication,
)
from .npu import NPU_INSTRUCTION_NAMES, encode_npu_instruction
from .parser import parse_string_literal, split_instruction, strip_comments
from .registers import HEX_REGISTER_INDEX, get_register, targets_display_register
from .reglist import is_register_list, parse_register_list
from .text import (
    build_text_expansion_metadata,
    parse_text_instruction,
    resolve_text_source_address,
)

SHIFT_TYPE_CODES: dict[str, int] = {
    "lsl": 0b00,
    "lsr": 0b01,
    "asr": 0b10,
    "ror": 0b11,
}
MAX_SHIFT_AMOUNT: int = 31

logger = logging.getLogger(__name__)

_SHIFTED_REGISTER_RE = re.compile(
    r"^(?P<reg>[A-Za-z][A-Za-z0-9]*)\s*(?:,\s*|\s+)"
    r"(?P<shift>LSL|LSR|ASR|ROR)\s+(?P<amount>.+)$",
    re.IGNORECASE,
)


def get_rn(tokens: list[str]) -> int:
    if tokens[1].strip().lower() == "hex":
        raise ValueError(
            "HEX cannot be encoded in the Rn field; move it to a general register "
            "or use HEX as Operand2"
        )
    return get_register(tokens[1])


def get_compare_rn(tokens: list[str]) -> int:
    if tokens[0].strip().lower() == "hex":
        raise ValueError(
            "HEX cannot be encoded in the Rn field; move it to a general register "
            "before comparing it"
        )
    return get_register(tokens[0])


def _is_shift_spec(token: str) -> bool:
    shift_name = token.strip().split(maxsplit=1)
    return bool(shift_name) and shift_name[0].lower() in SHIFT_TYPE_CODES


def _coalesce_shift_operands(params: list[str], expected_count: int) -> list[str]:
    if expected_count == 3 and len(params) == 4 and _is_shift_spec(params[3]):
        return [params[0], params[1], f"{params[2]}, {params[3]}"]
    if expected_count == 2 and len(params) == 3 and _is_shift_spec(params[2]):
        return [params[0], f"{params[1]}, {params[2]}"]
    return params


def _parse_shift_amount(token: str) -> int:
    raw = token.strip()
    if raw.startswith("#"):
        raw = raw[1:].strip()
    lowered = raw.lower()
    if lowered.startswith("vb"):
        amount = int(raw[2:], 2)
    elif lowered.startswith("v"):
        amount = int(raw[1:])
    else:
        amount = int(raw, 10)
    if not (0 <= amount <= MAX_SHIFT_AMOUNT):
        raise ValueError(f"Shift amount out of range (0..{MAX_SHIFT_AMOUNT}): {token}")
    return amount


def _encode_shifted_register_operand(token: str) -> int | None:
    match = _SHIFTED_REGISTER_RE.match(token.strip())
    if match is None:
        return None

    reg_token = match.group("reg").strip()
    shift_name = match.group("shift").lower()
    shift_amount = _parse_shift_amount(match.group("amount"))

    rm = get_register(reg_token)
    hex_source = int(reg_token.lower() == "hex")
    shift_code = SHIFT_TYPE_CODES[shift_name]
    return (shift_amount << 7) | (shift_code << 5) | (hex_source << 4) | rm


def _resolve_fp_literal_operand(
    token: str,
    symbol_table: dict[str, int],
) -> tuple[int, int, bool] | None:
    literal_info = fp16_literal_info(token)
    if literal_info is None:
        if token not in symbol_table and looks_like_fp_literal(token):
            raise ValueError(f"Invalid FP literal: {token}")
        return None
    key, _ = literal_info
    if key not in symbol_table:
        raise ValueError(f"FP literal pool entry missing for token: {token}")
    addr = symbol_table[key]
    if not (0 <= addr <= 0xFFF):
        raise ValueError(
            f"FP literal address out of 12-bit immediate range (0..4095): {token} -> {addr}"
        )
    return addr, 1, False


def check_operand2_constraints(
    base_op: str,
    op2_token: str,
    *,
    immediate: int,
    is_memory_access: bool,
    line: str,
) -> None:
    name = base_op.upper()
    if is_memory_access and base_op not in MEMORY_ACCESS_INSTRUCTIONS:
        raise ValueError(f"{name} does not support memory operands: {line}")
    if base_op not in FP_INSTRUCTIONS:
        return
    if is_memory_access:
        raise ValueError(f"{name} does not support memory operands: {line}")
    if _encode_shifted_register_operand(op2_token) is not None:
        raise ValueError(f"{name} does not support shifted Operand2: {line}")
    if immediate and fp16_literal_info(op2_token) is None:
        raise ValueError(
            f"{name} immediate Operand2 must be an F-prefixed literal (e.g. F1.5): {line}"
        )


def operand2_range_error(line: str, value: int) -> ValueError:
    return ValueError(
        f"Operand2 does not fit the 12-bit field (0..4095): {line} -> {value}.\n"
        "  V(expr) is evaluated directly into this field; it is not a "
        "wide-load form.\n"
        "  Use 'MOV Rd, =expr' to materialise a larger non-negative value, "
        "then use the register as Operand2 if needed.\n"
        "  For a variable above address 4095, use 'MOV Rn, =variable' and "
        "access it through '[Rn]'."
    )


def get_operand2(
    token: str,
    symbol_table: dict[str, int] | None = None,
    *,
    allow_fp_literal: bool = False,
) -> tuple[int, int, bool]:
    if symbol_table is None:
        symbol_table = {}

    token = token.strip()

    if allow_fp_literal:
        fp_literal = _resolve_fp_literal_operand(token, symbol_table)
        if fp_literal is not None:
            return fp_literal

    if token.startswith("[") and token.endswith("]"):
        ref = token[1:-1].strip()
        if ref in symbol_table:
            return symbol_table[ref], 1, True
        matrix_key = get_matrix_symbol_key(ref, symbol_table)
        if matrix_key is not None:
            return symbol_table[matrix_key], 1, True
        lowered = ref.lower()
        if lowered == "hex":
            return HEX_REGISTER_INDEX | 0x10, 0, True
        if lowered in REGISTER_ALIASES or re.fullmatch(r"r\d+", lowered) or lowered == "le":
            return get_register(ref), 0, True
        raise ValueError(f"Undefined variable, label, or register memory reference: {ref}")

    if token in symbol_table:
        return symbol_table[token], 1, False

    matrix_key = get_matrix_symbol_key(token, symbol_table)
    if matrix_key is not None:
        return symbol_table[matrix_key], 1, False

    if token and token[0] in {'"', "'"}:
        literal = parse_string_literal(token)
        if literal is not None:
            encoded = literal.encode("utf-8")
            if len(encoded) != 1:
                raise ValueError(
                    f"String literal immediate must encode to exactly one byte: {token}"
                )
            return encoded[0], 1, False

    lowered = token.lower()
    if lowered.startswith("v(") and token.endswith(")"):
        return evaluate_expression(token[2:-1], symbol_table), 1, False
    if lowered.startswith("vb"):
        return int(token[2:], 2), 1, False
    if lowered.startswith("v"):
        return int(token[1:]), 1, False

    shifted_reg = _encode_shifted_register_operand(token)
    if shifted_reg is not None:
        return shifted_reg, 0, False

    if lowered == "hex":
        return HEX_REGISTER_INDEX | 0x10, 0, False

    if lowered in REGISTER_ALIASES or re.fullmatch(r"r\d+", lowered) or lowered == "le":
        return get_register(token), 0, False

    raise ValueError(f"Undefined label or variable: {token}")


def encode_bootstrap_jump(entry_address: int) -> int:
    if not (0 <= entry_address <= MAX_BRANCH_TARGET):
        raise ValueError(
            "Program entry address does not fit the bootstrap's 20-bit branch "
            f"field (0..{MAX_BRANCH_TARGET}): {entry_address}"
        )
    return (
        (DEFAULT_CONDITION << 28)
        | (0b11 << 26)
        | (entry_address & MAX_BRANCH_TARGET)
    )


def _matrix_operand_address(
    token: str, matrix: MatrixLiteral, symbol_table: dict[str, int]
) -> int:
    stripped = token.strip()
    address = symbol_table.get(stripped)
    if address is None:
        address = symbol_table.get(canonicalize_matrix(matrix))
    if address is None:
        raise ValueError(f"Matrix operand address not found: {stripped!r}")
    return address


def _encode_matrix_multiply(
    params: list[str],
    symbol_table: dict[str, int],
    matrix_table: MatrixTable,
    *,
    condition: int,
    line: str,
) -> list[int] | None:
    left = resolve_matrix_operand(params[1], matrix_table)
    right = resolve_matrix_operand(params[2], matrix_table)
    if left is None and right is None:
        return None
    if left is None or right is None:
        raise ValueError(
            f"MUL matrix mode requires two matrix operands, "
            f"got '{params[1]}' and '{params[2]}'"
        )

    rd = get_register(params[0])
    flag = int(targets_display_register(params[0]))
    result_key = make_mmul_result_key(left, right)
    if result_key not in symbol_table:
        raise ValueError(f"Matrix result buffer missing for line: {line}")

    addr_a = _matrix_operand_address(params[1], left, symbol_table)
    addr_b = _matrix_operand_address(params[2], right, symbol_table)
    addr_r = symbol_table[result_key]
    rows_a, cols_a, cols_b = validate_matrix_multiplication(left, right)

    for descriptor, address in (
        ("matrix A", addr_a),
        ("matrix B", addr_b),
        ("matrix result", addr_r),
    ):
        if not (0 <= address <= MAX_MATRIX_ADDRESS):
            raise ValueError(
                f"{descriptor} address does not fit the 12-bit SETM field "
                f"(0..{MAX_MATRIX_ADDRESS}): {address} in line: {line}"
            )

    setup = DEFAULT_CONDITION << 28 | 0b01 << 26
    setma = setup | 0x2 << 21 | rows_a << 16 | cols_a << 12 | addr_a
    setmb = setup | 0x3 << 21 | cols_b << 12 | addr_b
    setmr = setup | 0x4 << 21 | addr_r
    mmul = condition << 28 | 0b01 << 26 | 0x5 << 21 | flag << 20 | rd << 12

    logger.info(
        "%s -> SETMA:%08X SETMB:%08X SETMR:%08X MMUL:%08X", line, setma, setmb, setmr, mmul
    )
    return [word & 0xFFFFFFFF for word in (setma, setmb, setmr, mmul)]


class _Fields(NamedTuple):
    rn: int
    rd: int
    operand2: int
    immediate: int
    is_memory_access: bool
    flag: int


def _encode_text(
    line: str,
    operation: str,
    params: list[str],
    symbol_table: dict[str, int],
    matrix_table: MatrixTable,
    *,
    condition: int,
    opcode: int,
) -> list[int]:
    instruction = parse_text_instruction(operation, params)
    meta = build_text_expansion_metadata(instruction)
    source_addr = resolve_text_source_address(instruction.source_token, symbol_table)
    word = (
        condition << 28
        | 0b01 << 26
        | 1 << 25
        | opcode << 21
        | meta.final_y_reg << 16
        | meta.final_x_reg << 12
        | source_addr
    ) & 0xFFFFFFFF

    setup = encode_asm(list(meta.setup_lines), symbol_table, matrix_table)
    logger.info("%s -> %08X", line, word)
    teardown = encode_asm(list(meta.teardown_lines), symbol_table, matrix_table)
    return [*setup, word, *teardown]


def _expand_pseudo_instruction(
    line: str,
    operation: str,
    base_op: str,
    params: list[str],
    symbol_table: dict[str, int],
    matrix_table: MatrixTable,
    *,
    condition: int,
    opcode: int,
) -> list[int] | None:
    if base_op in NPU_INSTRUCTION_NAMES:
        word = encode_npu_instruction(base_op, condition, params, symbol_table)
        logger.info("%s -> %08X", line, word)
        return [word]

    if base_op == "text":
        return _encode_text(
            line, operation, params, symbol_table, matrix_table,
            condition=condition, opcode=opcode,
        )

    if base_op == "mov" and len(params) == 2 and is_constant_load(params[1]):
        value = evaluate_expression(constant_load_expression(params[1]), symbol_table)
        expansion = expand_constant_load(params[0].strip(), value, condition)
        return encode_asm(expansion, symbol_table, matrix_table)

    if base_op in STACK_INSTRUCTIONS and len(params) == 1 and is_register_list(params[0]):
        elements = parse_register_list(params[0], descending=base_op == "push")
        return encode_asm(
            [f"{operation} {element}" for element in elements], symbol_table, matrix_table
        )

    return None


def _resolve_fields(
    base_op: str,
    params: list[str],
    param_count: int,
    symbol_table: dict[str, int],
    *,
    flag: int,
) -> _Fields:
    rn = rd = operand2 = immediate = 0
    is_memory_access = False
    allow_fp = base_op in FP_INSTRUCTIONS

    if param_count == 1:
        if base_op in STACK_INSTRUCTIONS:
            rd = get_register(params[0])
            flag = 1 if targets_display_register(params[0]) else flag
        else:
            operand2, immediate, is_memory_access = get_operand2(params[0], symbol_table)
        return _Fields(rn, rd, operand2, immediate, is_memory_access, flag)

    if param_count == 2:
        if base_op in COMPARE_INSTRUCTIONS:
            rn = get_compare_rn(params)
            flag = 1
        else:
            rd = get_register(params[0])
            flag = 1 if targets_display_register(params[0]) else flag
        operand2, immediate, is_memory_access = get_operand2(
            params[1], symbol_table, allow_fp_literal=allow_fp
        )
        return _Fields(rn, rd, operand2, immediate, is_memory_access, flag)

    rd = get_register(params[0])
    flag = 1 if targets_display_register(params[0]) else flag
    if base_op in SHIFT_PSEUDO_INSTRUCTIONS:
        synthetic = f"{params[1]}, {base_op.upper()} {params[2]}"
        operand2, immediate, is_memory_access = get_operand2(synthetic, symbol_table)
    else:
        rn = get_rn(params)
        operand2, immediate, is_memory_access = get_operand2(
            params[2], symbol_table, allow_fp_literal=allow_fp
        )
    return _Fields(rn, rd, operand2, immediate, is_memory_access, flag)


def _instruction_class(base_op: str, *, is_memory_access: bool) -> int:
    if base_op in EXT_CLASS_INSTRUCTIONS:
        return 1
    if base_op in MEM_CLASS_INSTRUCTIONS or is_memory_access:
        return 2
    if base_op in BR_CLASS_INSTRUCTIONS:
        return 3
    return 0


def encode_asm(
    instructions: list[str],
    symbol_table: dict[str, int] | None = None,
    matrix_table: MatrixTable | None = None,
) -> list[int]:
    if symbol_table is None:
        symbol_table = {}
    if matrix_table is None:
        matrix_table = {}

    output: list[int] = []

    for index, raw_line in enumerate(instructions):
        line = strip_comments(raw_line)
        if not line:
            continue

        operation, params = split_instruction(line)
        decoded = decode_operation(operation)
        if decoded is None:
            raise ValueError(f"Invalid operation in line {index + 1}: {operation}")

        base_op, condition, flag, opcode, param_count = decoded

        expansion = _expand_pseudo_instruction(
            line, operation, base_op, params, symbol_table, matrix_table,
            condition=condition, opcode=opcode,
        )
        if expansion is not None:
            output.extend(expansion)
            continue

        params = _coalesce_shift_operands(params, param_count)
        if base_op in SHIFT_PSEUDO_INSTRUCTIONS and len(params) == 2:
            params = [params[0], params[0], params[1]]
        if len(params) != param_count:
            raise ValueError(
                f"{base_op.upper()} expects {param_count} operand(s), got {len(params)} "
                f"in line {index + 1}: {line}"
            )

        if base_op == "mul" and param_count == 3:
            matrix_words = _encode_matrix_multiply(
                params, symbol_table, matrix_table, condition=condition, line=line
            )
            if matrix_words is not None:
                output.extend(matrix_words)
                continue

        rn, rd, operand2, immediate, is_memory_access, flag = _resolve_fields(
            base_op, params, param_count, symbol_table, flag=flag
        )

        if base_op in MEMORY_OPERAND_INSTRUCTIONS and not is_memory_access:
            raise ValueError(
                f"{base_op.upper()} requires a memory operand like [var] "
                f"in line {index + 1}: {line}"
            )

        check_operand2_constraints(
            base_op,
            params[param_count - 1],
            immediate=immediate,
            is_memory_access=is_memory_access,
            line=line,
        )

        instr_class = _instruction_class(base_op, is_memory_access=is_memory_access)

        if base_op in CONTROL_FLOW_BRANCH_INSTRUCTIONS:
            if not immediate or is_memory_access:
                raise ValueError(
                    f"{base_op.upper()} requires a label or immediate target "
                    f"in line {index + 1}: {line}"
                )
            if not (0 <= operand2 <= MAX_BRANCH_TARGET):
                raise ValueError(
                    f"Branch target does not fit the 20-bit field "
                    f"(0..{MAX_BRANCH_TARGET}): {line} -> {operand2}"
                )
            rn = (operand2 >> 16) & 0xF
            rd = (operand2 >> 12) & 0xF
            operand2 &= 0xFFF

        if not (0 <= operand2 <= 0xFFF):
            raise operand2_range_error(line, operand2)

        word = (
            (condition    << 28)
            | (instr_class << 26)
            | (immediate   << 25)
            | (opcode      << 21)
            | (flag        << 20)
            | (rn          << 16)
            | (rd          << 12)
            | operand2
        )

        logger.info("%s -> %08X", line, word)
        output.append(word & 0xFFFFFFFF)

    return output
