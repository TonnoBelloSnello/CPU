import re

from .constants import REGISTER_ALIASES

LE_REGISTER_INDEX: int = 15  # shares PC's encoding; bit 20 selects
HEX_REGISTER_INDEX: int = 14

_NUMBERED_REGISTER_RE = re.compile(r"r(\d+)")


def get_register(token: str) -> int:
    token = token.strip().lower()
    if token in REGISTER_ALIASES:
        return REGISTER_ALIASES[token]
    if token == "le":
        return LE_REGISTER_INDEX
    if token == "hex":
        return HEX_REGISTER_INDEX
    match = _NUMBERED_REGISTER_RE.fullmatch(token)
    if match is not None:
        index = int(match.group(1))
        if 0 <= index <= 15:
            return index
        raise ValueError(f"Register index out of range (R0..R15): {token}")
    raise ValueError(f"Invalid register: {token}")


def targets_display_register(token: str) -> bool:
    return token.strip().lower() in {"le", "hex"}
