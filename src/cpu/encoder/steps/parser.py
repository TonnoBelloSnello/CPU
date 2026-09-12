import ast
import re
from functools import lru_cache

_SHIFT_HASH_PREFIX_RE = re.compile(r"(?:^|[\s,])(LSL|LSR|ASR|ROR)\s*$", re.IGNORECASE)
_SHIFT_INSTRUCTION_PREFIX_RE = re.compile(
    r"^\s*(LSL|LSR|ASR|ROR)\b.*(?:,|\s)\s*$",
    re.IGNORECASE,
)
_SHIFT_AMOUNT_AFTER_HASH_RE = re.compile(
    r"\s*(?:VB[01]+|V\d+|\d+)(?=$|[\s,])",
    re.IGNORECASE,
)


def _is_shift_amount_hash(line: str, index: int) -> bool:
    return (
        (
            _SHIFT_HASH_PREFIX_RE.search(line[:index]) is not None
            or _SHIFT_INSTRUCTION_PREFIX_RE.match(line[:index]) is not None
        )
        and _SHIFT_AMOUNT_AFTER_HASH_RE.match(line[index + 1 :]) is not None
    )


def find_comment_start(line: str) -> int | None:
    quote_char: str | None = None
    escape_next = False

    for index, ch in enumerate(line):
        if quote_char is not None:
            if escape_next:
                escape_next = False
            elif ch == "\\":
                escape_next = True
            elif ch == quote_char:
                quote_char = None
            continue

        if ch in {'"', "'"}:
            quote_char = ch
        elif ch == "#" and not _is_shift_amount_hash(line, index):
            return index

    return None


def strip_brackets(token: str) -> str:
    stripped = token.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped[1:-1].strip()
    return stripped


def strip_comments(line: str) -> str:
    comment_start = find_comment_start(line)
    uncommented = line if comment_start is None else line[:comment_start]
    return uncommented.strip()


def split_operands(operands_text: str) -> list[str]:
    operands: list[str] = []
    current: list[str] = []
    depths = {'(': 0, '[': 0, '{': 0}
    close_to_open = {')': '(', ']': '[', '}': '{'}
    in_string = False
    quote_char = ""
    escape_next = False

    for ch in operands_text:
        if in_string:
            current.append(ch)
            if escape_next:
                escape_next = False
            elif ch == "\\":
                escape_next = True
            elif ch == quote_char:
                in_string = False
            continue

        if ch in {'"', "'"}:
            in_string = True
            quote_char = ch
            current.append(ch)
        elif ch in depths:
            depths[ch] += 1
            current.append(ch)
        elif ch in close_to_open:
            depths[close_to_open[ch]] -= 1
            current.append(ch)
        elif ch == "," and not any(depths.values()):
            if operand := "".join(current).strip():
                operands.append(operand)
            current = []
        else:
            current.append(ch)

    if trailing := "".join(current).strip():
        operands.append(trailing)

    if in_string or any(depths.values()):
        raise ValueError(f"Malformed operand list: {operands_text}")
    return operands


def split_instruction(line: str) -> tuple[str, list[str]]:
    operation, operands = _split_instruction_cached(line)
    return operation, list(operands)


@lru_cache(maxsize=4096)
def _split_instruction_cached(line: str) -> tuple[str, tuple[str, ...]]:
    parts = line.strip().split(None, 1)
    if not parts:
        raise ValueError("Empty instruction")
    operation = parts[0]
    if len(parts) == 1:
        return operation, ()
    return operation, tuple(split_operands(parts[1]))


def parse_string_literal(token: str) -> str | None:
    return _parse_string_literal_cached(token.strip())


@lru_cache(maxsize=2048)
def _parse_string_literal_cached(token: str) -> str | None:
    if len(token) < 2:
        return None
    quote = token[0]
    if quote not in {'"', "'"} or token[-1] != quote:
        return None
    try:
        value = ast.literal_eval(token)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Invalid string literal: {token}") from exc
    if not isinstance(value, str):
        raise ValueError(f"Invalid string literal: {token}")
    return value
