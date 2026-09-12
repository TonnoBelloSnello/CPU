import math
import re
import struct

_FP_LITERAL_BODY_RE = re.compile(
    r"^(?:"
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    r"|[-+]?(?:inf|nan)"
    r")$",
    re.IGNORECASE,
)

FP16_QUIET_NAN = 0x7E00


def parse_fp_literal(token: str) -> float | None:
    raw = token.strip()
    if len(raw) < 2 or raw[0] not in {"F", "f"}:
        return None
    body = raw[1:].strip()
    if not body or _FP_LITERAL_BODY_RE.match(body) is None:
        return None
    return float(body)


def float_to_fp16_bits(value: float) -> int:
    if math.isnan(value):
        return FP16_QUIET_NAN
    try:
        packed = struct.pack(">e", value)
    except OverflowError:
        return 0xFC00 if math.copysign(1.0, value) < 0 else 0x7C00
    return int.from_bytes(packed, byteorder="big")


def fp16_bits_to_float(bits: int) -> float:
    return struct.unpack(">e", int(bits & 0xFFFF).to_bytes(2, byteorder="big"))[0]


def looks_like_fp_literal(token: str) -> bool:
    stripped = token.strip()
    if len(stripped) < 2 or stripped[0] not in {"F", "f"}:
        return False
    return any(ch.isdigit() or ch in ".+-" for ch in stripped[1:])


def fp16_literal_key_from_bits(bits: int) -> str:
    return f"__fp16_{bits & 0xFFFF:04X}"


def fp16_literal_info(token: str) -> tuple[str, int] | None:
    parsed = parse_fp_literal(token)
    if parsed is None:
        return None
    bits = float_to_fp16_bits(parsed)
    return fp16_literal_key_from_bits(bits), bits
