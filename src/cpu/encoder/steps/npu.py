from __future__ import annotations

import re
from typing import Final

NPU_VLD: Final = 0x0
NPU_VST: Final = 0x1
NPU_VDOT: Final = 0x2
NPU_VSUM: Final = 0x3
NPU_VMAXR: Final = 0x4
NPU_VDUP: Final = 0x5
NPU_VEXT: Final = 0x6
NPU_VINS: Final = 0x7
NPU_ACLR: Final = 0x8
NPU_ASET: Final = 0x9
NPU_AGET: Final = 0xA
NPU_AGETS: Final = 0xB
NPU_AQMUL: Final = 0xC
NPU_ARSHR: Final = 0xD
NPU_NPUCFG: Final = 0xE
NPU_NPURUN: Final = 0xF

NPU_LANES: Final = 8
NPU_VREGS: Final = 8
NPU_ACCS: Final = 4
NPU_PATCH_DEPTH: Final = 512

NPU_INSTRUCTIONS: Final[dict[str, tuple[int, int]]] = {
    "vld": (NPU_VLD, 2),
    "vst": (NPU_VST, 2),
    "vdot": (NPU_VDOT, 3),
    "vsum": (NPU_VSUM, 2),
    "vmaxr": (NPU_VMAXR, 2),
    "vdup": (NPU_VDUP, 2),
    "vext": (NPU_VEXT, 3),
    "vins": (NPU_VINS, 3),
    "aclr": (NPU_ACLR, 1),
    "aset": (NPU_ASET, 2),
    "aget": (NPU_AGET, 2),
    "agets": (NPU_AGETS, 2),
    "aqmul": (NPU_AQMUL, 2),
    "arshr": (NPU_ARSHR, 2),
    "npucfg": (NPU_NPUCFG, 2),
    "npurun": (NPU_NPURUN, 1),
}

NPU_INSTRUCTION_NAMES: Final[frozenset[str]] = frozenset(NPU_INSTRUCTIONS)

NPU_CONFIG_FIELDS: Final[dict[str, int]] = {
    "mode": 0,
    "flags": 1,
    "in_base": 2,
    "in_w": 3,
    "in_h": 4,
    "in_c": 5,
    "w_base": 6,
    "b_base": 7,
    "out_base": 8,
    "out_w": 9,
    "out_h": 10,
    "out_c": 11,
    "k_w": 12,
    "k_h": 13,
    "stride": 14,
    "pad": 15,
    "in_zp": 16,
    "out_zp": 17,
    "mult": 18,
    "shift": 19,
    "act_min": 20,
    "act_max": 21,
    "acc_base": 22,
    "lut_base": 23,
}

NPU_BUILTIN_CONSTANTS: Final[dict[str, int]] = {
    "NPU_CONV": 0,
    "NPU_DEPTHWISE": 1,
    "NPU_MAXPOOL": 2,
    "NPU_AVGPOOL": 3,
    "NPU_LUT": 4,
    "NPU_ARGMAX": 5,
    "NPU_ACC_IN": 1,
    "NPU_ACC_OUT": 2,
    "NPU_NO_BIAS": 4,
    "NPU_OK": 0,
    "NPU_ERR_SHAPE": 1,
    "NPU_ERR_PATCH": 2,
    "NPU_LANES": NPU_LANES,
    "NPU_PATCH_DEPTH": NPU_PATCH_DEPTH,
}

_VECTOR_RE = re.compile(r"^q(\d+)$", re.IGNORECASE)
_ACCUMULATOR_RE = re.compile(r"^a(\d+)$", re.IGNORECASE)


def parse_vector_register(token: str) -> int | None:
    match = _VECTOR_RE.fullmatch(token.strip())
    if match is None:
        return None
    index = int(match.group(1))
    if index >= NPU_VREGS:
        raise ValueError(
            f"Vector register out of range (Q0..Q{NPU_VREGS - 1}): {token.strip()}"
        )
    return index


def parse_accumulator(token: str) -> int | None:
    match = _ACCUMULATOR_RE.fullmatch(token.strip())
    if match is None:
        return None
    index = int(match.group(1))
    if index >= NPU_ACCS:
        raise ValueError(
            f"Accumulator out of range (A0..A{NPU_ACCS - 1}): {token.strip()}"
        )
    return index


def is_npu_register_token(token: str) -> bool:
    stripped = token.strip()
    return (
        _VECTOR_RE.fullmatch(stripped) is not None
        or _ACCUMULATOR_RE.fullmatch(stripped) is not None
    )


def _require_vector(token: str, *, role: str) -> int:
    index = parse_vector_register(token)
    if index is None:
        raise ValueError(f"{role} must be a vector register Q0..Q{NPU_VREGS - 1}: {token.strip()}")
    return index


def _require_accumulator(token: str, *, role: str) -> int:
    index = parse_accumulator(token)
    if index is None:
        raise ValueError(f"{role} must be an accumulator A0..A{NPU_ACCS - 1}: {token.strip()}")
    return index


def _require_immediate(token: str, symbol_table: dict[str, int], *, role: str) -> int:
    from .encoder import get_operand2

    value, immediate, is_memory_access = get_operand2(token, symbol_table)
    if not immediate or is_memory_access:
        raise ValueError(f"{role} must be an immediate value: {token.strip()}")
    return value


def resolve_config_field(token: str) -> int:
    name = token.strip().lower()
    if name not in NPU_CONFIG_FIELDS:
        known = ", ".join(sorted(field.upper() for field in NPU_CONFIG_FIELDS))
        raise ValueError(
            f"Unknown NPU configuration field '{token.strip()}'; expected one of: {known}"
        )
    return NPU_CONFIG_FIELDS[name]


def encode_npu_instruction(
    base_op: str,
    condition: int,
    params: list[str],
    symbol_table: dict[str, int],
) -> int:
    from .encoder import get_operand2, get_register

    sub_opcode, param_count = NPU_INSTRUCTIONS[base_op]
    if len(params) != param_count:
        raise ValueError(
            f"{base_op.upper()} expects {param_count} operand(s), got {len(params)}"
        )

    flag = 0
    rd = 0
    operand2 = 0
    immediate = 1

    if sub_opcode in (NPU_VLD, NPU_VST):
        rd = _require_vector(params[0], role=f"{base_op.upper()} first operand")
        operand2, immediate, is_memory_access = get_operand2(params[1], symbol_table)
        if not is_memory_access:
            raise ValueError(
                f"{base_op.upper()} requires a memory operand like [Rn] or [buffer]: "
                f"{params[1].strip()}"
            )

    elif sub_opcode == NPU_VDOT:
        rd = _require_accumulator(params[0], role="VDOT destination")
        left = _require_vector(params[1], role="VDOT first source")
        right = _require_vector(params[2], role="VDOT second source")
        operand2 = left | (right << 3)

    elif sub_opcode == NPU_VSUM:
        rd = _require_accumulator(params[0], role="VSUM destination")
        operand2 = _require_vector(params[1], role="VSUM source")

    elif sub_opcode == NPU_VMAXR:
        rd = get_register(params[0])
        operand2 = _require_vector(params[1], role="VMAXR source")

    elif sub_opcode == NPU_VDUP:
        rd = _require_vector(params[0], role="VDUP destination")
        operand2, immediate, is_memory_access = get_operand2(params[1], symbol_table)
        if is_memory_access:
            raise ValueError(f"VDUP does not support memory operands: {params[1].strip()}")

    elif sub_opcode == NPU_VEXT:
        rd = get_register(params[0])
        source = _require_vector(params[1], role="VEXT source")
        lane = _require_immediate(params[2], symbol_table, role="VEXT lane index")
        _check_lane(lane)
        operand2 = source | (lane << 4)

    elif sub_opcode == NPU_VINS:
        rd = _require_vector(params[0], role="VINS destination")
        source = get_register(params[1])
        lane = _require_immediate(params[2], symbol_table, role="VINS lane index")
        _check_lane(lane)
        operand2 = source | (lane << 4)

    elif sub_opcode == NPU_ACLR:
        rd = _require_accumulator(params[0], role="ACLR destination")

    elif sub_opcode in (NPU_ASET, NPU_AQMUL, NPU_ARSHR):
        rd = _require_accumulator(params[0], role=f"{base_op.upper()} destination")
        operand2, immediate, is_memory_access = get_operand2(params[1], symbol_table)
        if is_memory_access:
            raise ValueError(
                f"{base_op.upper()} does not support memory operands: {params[1].strip()}"
            )

    elif sub_opcode in (NPU_AGET, NPU_AGETS):
        rd = get_register(params[0])
        operand2 = _require_accumulator(params[1], role=f"{base_op.upper()} source")

    elif sub_opcode == NPU_NPUCFG:
        index = resolve_config_field(params[0])
        rd = index & 0xF
        flag = (index >> 4) & 0x1
        operand2, immediate, is_memory_access = get_operand2(params[1], symbol_table)
        if is_memory_access:
            raise ValueError(f"NPUCFG does not support memory operands: {params[1].strip()}")

    else:
        rd = get_register(params[0])

    if not (0 <= operand2 <= 0xFFF):
        raise ValueError(
            f"{base_op.upper()} Operand2 does not fit the 12-bit field (0..4095): "
            f"{operand2}.\n"
            "  Materialise it with 'MOV Rd, =expr' and pass the register instead."
        )

    return (
        (condition << 28)
        | (0b10 << 26)
        | (immediate << 25)
        | (0x0 << 21)
        | (flag << 20)
        | (sub_opcode << 16)
        | (rd << 12)
        | operand2
    ) & 0xFFFFFFFF


def _check_lane(lane: int) -> None:
    if not (0 <= lane < NPU_LANES):
        raise ValueError(f"Lane index out of range (0..{NPU_LANES - 1}): {lane}")


__all__ = [
    "NPU_ACCS",
    "NPU_BUILTIN_CONSTANTS",
    "NPU_CONFIG_FIELDS",
    "NPU_INSTRUCTIONS",
    "NPU_INSTRUCTION_NAMES",
    "NPU_LANES",
    "NPU_PATCH_DEPTH",
    "NPU_VREGS",
    "encode_npu_instruction",
    "is_npu_register_token",
    "parse_accumulator",
    "parse_vector_register",
    "resolve_config_field",
]
