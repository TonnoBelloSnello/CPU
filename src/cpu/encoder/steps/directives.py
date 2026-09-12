from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .npu import NPU_BUILTIN_CONSTANTS
from .parser import strip_comments

_CONST_RE = re.compile(
    r"^const\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<expr>.+)$", re.IGNORECASE
)
_INCLUDE_RE = re.compile(r"^include(?:\s+(?P<target>.*))?$", re.IGNORECASE)

MAX_INCLUDE_DEPTH = 16

_BINARY_OPS: dict[type[ast.operator], Callable[[int, int], int]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Div: operator.floordiv,
    ast.Mod: operator.mod,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[int], int]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,
}


class DirectiveError(ValueError):
    pass


def evaluate_expression(text: str, constants: dict[str, int]) -> int:
    source = text.strip()
    if not source:
        raise DirectiveError("Empty constant expression")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise DirectiveError(f"Invalid constant expression: {source}") from exc
    try:
        return _evaluate_node(tree.body, constants, source)
    except ArithmeticError as exc:
        raise DirectiveError(f"Invalid arithmetic in constant expression: {source}: {exc}") from exc


def _evaluate_node(node: ast.AST, constants: dict[str, int], source: str) -> int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            raise DirectiveError(f"Constant expressions are integer-only: {source}")
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in constants:
            raise DirectiveError(f"Undefined constant '{node.id}' in: {source}")
        return constants[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        left = _evaluate_node(node.left, constants, source)
        right = _evaluate_node(node.right, constants, source)
        if type(node.op) in {ast.Div, ast.FloorDiv, ast.Mod} and right == 0:
            raise DirectiveError(f"Division by zero in: {source}")
        if type(node.op) in {ast.LShift, ast.RShift} and right < 0:
            raise DirectiveError(f"Shift amount must be non-negative in: {source}")
        return _BINARY_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_evaluate_node(node.operand, constants, source))
    raise DirectiveError(f"Unsupported syntax in constant expression: {source}")


def _include_target(raw: str, line_number: int) -> str:
    target = raw.strip()
    if len(target) >= 2 and target[0] == target[-1] and target[0] in {'"', "'"}:
        return target[1:-1]
    raise DirectiveError(f"include expects a quoted file name in line {line_number}: {raw}")


@dataclass(frozen=True, slots=True)
class SourceLine:
    raw: str
    line: int
    path: Path | None = None


@dataclass(slots=True)
class ExpandedSource:
    lines: list[SourceLine] = field(default_factory=list)
    dependencies: set[Path] = field(default_factory=set)


def expand_source(
    lines: list[str],
    base_dir: Path | None,
    *,
    source_path: Path | None = None,
    documents: Mapping[Path, str] | None = None,
    on_error: Callable[[SourceLine, DirectiveError], None] | None = None,
) -> ExpandedSource:
    result = ExpandedSource()
    overlays = {path.resolve(): text for path, text in (documents or {}).items()}

    def visit(
        source: list[str], directory: Path | None, origin: Path | None, stack: tuple[Path, ...]
    ) -> None:
        for index, raw in enumerate(source):
            entry = SourceLine(raw, index, origin)
            match = _INCLUDE_RE.match(strip_comments(raw).strip())
            if match is None:
                result.lines.append(entry)
                continue
            try:
                target = _include_target(match.group("target") or "", index + 1)
                if directory is None:
                    raise DirectiveError(
                        "include is only available when assembling a file: "
                        f"cannot resolve {target!r} without a source directory"
                    )
                path = (directory / target).resolve()
                result.dependencies.add(path)
                if path in stack:
                    chain = " -> ".join(p.name for p in (*stack, path))
                    raise DirectiveError(f"Circular include: {chain}")
                if len(stack) >= MAX_INCLUDE_DEPTH:
                    raise DirectiveError(f"include nested deeper than {MAX_INCLUDE_DEPTH} levels")
                if path in overlays:
                    text = overlays[path]
                elif path.is_file():
                    text = path.read_text(encoding="utf-8")
                else:
                    raise DirectiveError(f"Included file not found: {target}")
            except (OSError, UnicodeError, DirectiveError) as exc:
                error = DirectiveError(str(exc))
                if on_error is None:
                    raise error from exc
                on_error(entry, error)
                continue
            visit(text.splitlines(), path.parent, path, (*stack, path))

    visit(lines, base_dir, source_path.resolve() if source_path else None, ())
    return result


def expand_includes(lines: list[str], base_dir: Path | None) -> list[str]:
    return [entry.raw for entry in expand_source(lines, base_dir).lines]


def extract_constants(
    lines: list[str], *, on_error: Callable[[int, DirectiveError], None] | None = None
) -> tuple[list[str], dict[str, int]]:
    constants: dict[str, int] = {}
    scope: dict[str, int] = dict(NPU_BUILTIN_CONSTANTS)
    remaining: list[str] = []

    for index, raw in enumerate(lines):
        stripped = strip_comments(raw).strip()
        match = _CONST_RE.match(stripped) if stripped else None
        if match is None:
            remaining.append(raw)
            continue

        name = match.group("name")
        try:
            if name.startswith("__"):
                raise DirectiveError(f"Constant '{name}' uses the reserved internal namespace '__'")
            if name in constants:
                raise DirectiveError(f"Duplicate constant declaration: '{name}'")
            if name in NPU_BUILTIN_CONSTANTS:
                raise DirectiveError(f"Constant '{name}' shadows a built-in NPU name")
            value = evaluate_expression(match.group("expr"), scope)
        except DirectiveError as exc:
            error = DirectiveError(f"{exc} (line {index + 1})")
            if on_error is None:
                raise error from exc
            on_error(index, error)
            continue
        constants[name] = value
        scope[name] = value

    return remaining, constants


def preprocess(lines: list[str], base_dir: Path | None = None) -> tuple[list[str], dict[str, int]]:
    remaining, constants = extract_constants(expand_includes(lines, base_dir))
    return remaining, {**NPU_BUILTIN_CONSTANTS, **constants}


def is_directive_line(text: str) -> bool:
    stripped = strip_comments(text).strip()
    if not stripped:
        return False
    return _CONST_RE.match(stripped) is not None or _INCLUDE_RE.match(stripped) is not None
