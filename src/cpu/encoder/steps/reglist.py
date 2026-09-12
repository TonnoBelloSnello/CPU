import re

from .parser import split_operands
from .registers import get_register

_LIST_RE = re.compile(r"^\{(?P<body>.*)\}$", re.DOTALL)
_RANGE_RE = re.compile(
    r"^(?P<first>[A-Za-z][A-Za-z0-9]*)\s*-\s*(?P<last>[A-Za-z][A-Za-z0-9]*)$"
)
_NUMBERED_REGISTER_RE = re.compile(r"[Rr]\d+")


def is_register_list(token: str) -> bool:
    return _LIST_RE.match(token.strip()) is not None


def _expand_range(first: str, last: str, raw: str) -> list[str]:
    for endpoint in (first, last):
        if _NUMBERED_REGISTER_RE.fullmatch(endpoint.strip()) is None:
            raise ValueError(
                f"Register range endpoints must be R-numbered registers: {raw}"
            )
    first_index = get_register(first)
    last_index = get_register(last)
    if first_index > last_index:
        raise ValueError(f"Register range must run low to high: {raw}")
    return [f"R{index}" for index in range(first_index, last_index + 1)]


def parse_register_list(token: str, *, descending: bool) -> list[str]:
    match = _LIST_RE.match(token.strip())
    if match is None:
        raise ValueError(f"Not a register list: {token}")

    body = match.group("body").strip()
    if not body:
        raise ValueError(f"Empty register list: {token}")

    elements: list[str] = []
    for element in split_operands(body):
        range_match = _RANGE_RE.match(element)
        if range_match is not None:
            elements.extend(
                _expand_range(range_match.group("first"), range_match.group("last"), token)
            )
        else:
            elements.append(element.strip())

    seen: set[int] = set()
    for element in elements:
        index = get_register(element)
        if index in seen:
            raise ValueError(f"Register listed twice: {element} in {token}")
        seen.add(index)

    elements.sort(key=get_register, reverse=descending)
    return elements


def register_list_length(token: str) -> int:
    return len(parse_register_list(token, descending=True))
