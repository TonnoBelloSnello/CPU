from .constants import (
    BINARY_IMMEDIATE_RE,
    CONDITION_SUFFIX_BY_CODE,
    DECIMAL_IMMEDIATE_RE,
    REGISTER_ALIAS_NAMES,
    REGISTER_TOKEN_RE,
    decode_operation,
)
from .parser import split_operands

THREE_OPERAND_INSTR = {
    "and", "eor", "sub", "rsb", "add", "mul", "div", "adc", "sbc", "rsc",
    "orr", "bic",
    "fadd", "fsub", "fmul", "fdiv",
    "max", "min", "madd",
    "pixelnb",
    "qadd", "qsub", "ssat", "usat", "qrdmulh", "rshr", "relu",
}

TWO_OPERAND_INSTR = {
    "tst", "teq", "cmp", "cmn", "fcmp", "save", "savem", "movm", "abs", "waitk",
    "waitknb", "sxtb",
}

TWO_OPERAND_MOV_INSTR = {
    "mov", "mvn", "fmov"
}



def _normalize_operand(op: str) -> str:
    up = op.upper()
    if (
        up in REGISTER_ALIAS_NAMES
        or REGISTER_TOKEN_RE.fullmatch(up) is not None
        or DECIMAL_IMMEDIATE_RE.fullmatch(up) is not None
        or BINARY_IMMEDIATE_RE.fullmatch(up) is not None
    ):
        return up
    return op


def _decoded_mnemonic(mnemonic: str) -> tuple[str, str]:
    decoded = decode_operation(mnemonic)
    if decoded is None:
        return mnemonic.lower(), mnemonic.upper()
    base, condition, _, _, _ = decoded
    suffix = CONDITION_SUFFIX_BY_CODE.get(condition, "")
    return base, f"{base.upper()}{suffix}"


def _mnemonic_with_base(base: str, condition: int) -> str:
    return f"{base.upper()}{CONDITION_SUFFIX_BY_CODE.get(condition, '')}"


def _condition_of(mnemonic: str) -> int:
    decoded = decode_operation(mnemonic)
    if decoded is None:
        raise ValueError(f"Unrecognized mnemonic: {mnemonic}")
    return decoded[1]


def _negative_immediate_info(operand: str) -> tuple[int, bool] | None:
    up = operand.upper()
    if up.startswith("VB-") and BINARY_IMMEDIATE_RE.fullmatch(up) is not None:
        return int(up[3:], 2), True
    if up.startswith("V-") and DECIMAL_IMMEDIATE_RE.fullmatch(up) is not None:
        return int(up[2:], 10), False
    return None


def _format_immediate(value: int, *, binary: bool) -> str:
    return f"VB{value:b}" if binary else f"V{value}"


def _rewrite_negative_arithmetic(
    mnemonic: str,
    operand: str,
) -> tuple[str, str]:
    info = _negative_immediate_info(operand)
    if info is None:
        return mnemonic, operand
    magnitude, is_binary = info

    decoded = decode_operation(mnemonic)
    if decoded is None:
        return mnemonic, operand
    base, condition, _, _, _ = decoded
    if magnitude == 0:
        return mnemonic, _format_immediate(0, binary=is_binary)

    if base == "add":
        replacement, value = "sub", magnitude
    elif base == "sub":
        replacement, value = "add", magnitude
    elif base == "qadd":
        replacement, value = "qsub", magnitude
    elif base == "qsub":
        replacement, value = "qadd", magnitude
    elif base == "adc":
        replacement, value = "sbc", magnitude - 1
    elif base == "sbc":
        replacement, value = "adc", magnitude - 1
    else:
        raise ValueError(
            f"{base.upper()} cannot represent negative immediate {operand} "
            "without changing program semantics; materialize it in a register"
        )
    return _mnemonic_with_base(replacement, condition), _format_immediate(value, binary=is_binary)


def normalize_arm_instructions(instructions: list[str]) -> list[str]:
    return [normalize_arm_instruction(instruction) for instruction in instructions]


def normalize_arm_instruction(instruction: str) -> str:
    line = instruction.strip()
    parts = line.split(None, 1)
    if len(parts) == 0:
        return instruction

    mnemo = parts[0].upper()
    base_mnemo, canonical_mnemo = _decoded_mnemonic(mnemo)
    if len(parts) == 1:
        return instruction

    ops_str = parts[1].strip()

    try:
        operands = split_operands(ops_str)
    except ValueError:
        return instruction

    operands = [_normalize_operand(op) for op in operands]

    if base_mnemo in THREE_OPERAND_INSTR:
        if len(operands) == 2:
            operands = [operands[0], operands[0], operands[1]]
        if len(operands) != 3:
            return f"{mnemo} {ops_str}"

        rd, rn, rm_or_imm = operands
        if _negative_immediate_info(rm_or_imm) is not None:
            canonical_mnemo, rm_or_imm = _rewrite_negative_arithmetic(
                canonical_mnemo, rm_or_imm
            )
        return f"{canonical_mnemo} {rd}, {rn}, {rm_or_imm}"

    if base_mnemo in TWO_OPERAND_INSTR:
        if len(operands) == 2 and (info := _negative_immediate_info(operands[1])) is not None:
            magnitude, is_binary = info
            if magnitude == 0:
                operands[1] = _format_immediate(0, binary=is_binary)
            elif base_mnemo in {"cmp", "cmn"}:
                replacement = "cmn" if base_mnemo == "cmp" else "cmp"
                canonical_mnemo = _mnemonic_with_base(replacement, _condition_of(canonical_mnemo))
                operands[1] = _format_immediate(magnitude, binary=is_binary)
            elif base_mnemo == "abs":
                operands[1] = _format_immediate(magnitude, binary=is_binary)
            else:
                raise ValueError(
                    f"{base_mnemo.upper()} cannot represent negative immediate {operands[1]} "
                    "without changing program semantics; materialize it in a register"
                )
        return f"{canonical_mnemo} {', '.join(operands)}"

    if base_mnemo in TWO_OPERAND_MOV_INSTR and len(operands) == 2:
        info = _negative_immediate_info(operands[1])
        if info is not None:
            rd, rm_or_imm = operands
            magnitude, is_binary = info
            if base_mnemo == "fmov":
                raise ValueError(
                    f"FMOV integer immediate {rm_or_imm} is invalid; use an F-prefixed literal"
                )
            if magnitude == 0:
                return f"{canonical_mnemo} {rd}, {_format_immediate(0, binary=is_binary)}"
            replacement = "mvn" if base_mnemo == "mov" else "mov"
            new_mnemo = _mnemonic_with_base(replacement, _condition_of(canonical_mnemo))
            return f"{new_mnemo} {rd}, {_format_immediate(magnitude - 1, binary=is_binary)}"

    return f"{mnemo} {ops_str}"
