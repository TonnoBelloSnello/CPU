import re
from functools import lru_cache
from typing import Final

from .npu import NPU_INSTRUCTIONS

InstructionInfo = tuple[int, int]  # (opcode, parameter_count)

INSTRUCTION_SET: Final[dict[str, InstructionInfo]] = {
    "and": (0x0, 3),
    "eor": (0x1, 3),
    "sub": (0x2, 3),
    "rsb": (0x3, 3),
    "add": (0x4, 3),
    "mul": (0x1, 3),
    "div": (0xF, 3),
    "adc": (0x5, 3),
    "sbc": (0x6, 3),
    "rsc": (0x7, 3),
    "tst": (0x8, 2),
    "teq": (0x9, 2),
    "cmp": (0xA, 2),
    "cmn": (0xB, 2),
    "orr": (0xC, 3),
    "savem": (0xA, 2),
    "movm": (0xB, 2),
    "save": (0xC, 2),
    "mov": (0xD, 2),
    "bic": (0xE, 3),
    "mvn": (0xF, 2),
    "push": (0xE, 1),
    "pop": (0xF, 1),
    "wait": (0x0, 1),
    "waitk": (0xD, 2),
    "pixel": (0x6, 3),
    "fadd": (0x7, 3),
    "fsub": (0x8, 3),
    "fmul": (0x9, 3),
    "fdiv": (0xA, 3),
    "fcmp": (0xB, 2),
    "fmov": (0xC, 2),
    "text": (0xE, 3),
    "b":   (0x0, 1),
    "bl":  (0x1, 1),
    "abs": (0x2, 2),
    "max": (0x3, 3),
    "min": (0x4, 3),
    "madd": (0x5, 3),
    "pixelnb": (0x6, 3),
    "waitknb": (0x7, 2),
    "qadd": (0x8, 3),
    "qsub": (0x9, 3),
    "ssat": (0xA, 3),
    "usat": (0xB, 3),
    "qrdmulh": (0xC, 3),
    "rshr": (0xD, 3),
    "relu": (0xE, 3),
    "sxtb": (0xF, 2),
    "lsl": (0xD, 3),
    "lsr": (0xD, 3),
    "asr": (0xD, 3),
    "ror": (0xD, 3),
}

INSTRUCTION_SET.update(
    {name: (0x0, param_count) for name, (_, param_count) in NPU_INSTRUCTIONS.items()}
)

CONDITION_SET: Final[dict[str, int]] = {
    "eq": 0x0, "ne": 0x1,
    "cs": 0x2, "cc": 0x3,
    "mi": 0x4, "pl": 0x5,
    "vs": 0x6, "vc": 0x7,
    "hi": 0x8, "ls": 0x9,
    "ge": 0xa, "lt": 0xb,
    "gt": 0xc, "le": 0xd,
    "al": 0xe, "nv": 0xf,
}

REGISTER_ALIASES: Final[dict[str, int]] = {
    "sp": 13,
    "lr": 14,
    "pc": 15,
}
REGISTER_ALIAS_NAMES: Final[frozenset[str]] = frozenset({"SP", "LR", "PC", "LE", "HEX"})
REGISTER_TOKEN_RE: Final = re.compile(r"R\d+", re.IGNORECASE)
DECIMAL_IMMEDIATE_RE: Final = re.compile(r"V[+-]?\d+", re.IGNORECASE)
BINARY_IMMEDIATE_RE: Final = re.compile(r"VB[+-]?[01]+", re.IGNORECASE)

DEFAULT_CONDITION: Final[int] = CONDITION_SET["al"]
CONDITION_SUFFIX_BY_CODE: Final[dict[int, str]] = {
    code: suffix.upper()
    for suffix, code in CONDITION_SET.items()
    if code != DEFAULT_CONDITION
}
STACK_INSTRUCTIONS: Final[set[str]] = {"push", "pop"}
BR_CLASS_INSTRUCTIONS: Final[set[str]] = {
    "b", "bl", "abs", "max", "min", "madd", "pixelnb", "waitknb",
    "qadd", "qsub", "ssat", "usat", "qrdmulh", "rshr", "relu", "sxtb",
}
CONTROL_FLOW_BRANCH_INSTRUCTIONS: Final[set[str]] = {"b", "bl"}
BRANCH_TARGET_BITS: Final[int] = 20
MAX_BRANCH_TARGET: Final[int] = (1 << BRANCH_TARGET_BITS) - 1
COMPARE_INSTRUCTIONS: Final[set[str]] = {"tst", "teq", "cmp", "cmn", "fcmp"}
FP_INSTRUCTIONS: Final[set[str]] = {"fadd", "fsub", "fmul", "fdiv", "fcmp", "fmov"}
SHIFT_PSEUDO_INSTRUCTIONS: Final[set[str]] = {"lsl", "lsr", "asr", "ror"}
MEMORY_OPERAND_INSTRUCTIONS: Final[set[str]] = {"save", "savem", "movm"}
MEMORY_ACCESS_INSTRUCTIONS: Final[set[str]] = {"mov", "save", "savem", "movm"}
EXT_CLASS_INSTRUCTIONS: Final[set[str]] = {"wait", "waitk", "mul", "div", "pixel"} | FP_INSTRUCTIONS
MEM_CLASS_INSTRUCTIONS: Final[set[str]] = STACK_INSTRUCTIONS | {"savem", "movm"}


@lru_cache(maxsize=512)
def decode_operation(operation: str) -> tuple[str, int, int, int, int] | None:
    lowered = operation.lower()

    def _decode_core(core_op: str, condition_code: int) -> tuple[str, int, int, int, int] | None:
        exact_info = INSTRUCTION_SET.get(core_op)
        if exact_info is None:
            return None
        opcode, param_count = exact_info
        return core_op, condition_code, 0, opcode, param_count

    if len(lowered) >= 2:
        condition = CONDITION_SET.get(lowered[-2:])
        if condition is not None:
            if len(lowered) < 3:
                return None
            decoded = _decode_core(lowered[:-2], condition)
            if decoded is not None:
                return decoded

    return _decode_core(lowered, DEFAULT_CONDITION)
