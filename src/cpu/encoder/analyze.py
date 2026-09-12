from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from .assemble import SourceEntry, SourceError, layout_source
from .steps.directives import DirectiveError, SourceLine, expand_source, extract_constants
from .steps.encoder import encode_asm
from .steps.npu import NPU_BUILTIN_CONSTANTS
from .steps.parser import find_comment_start
from .steps.prettify import normalize_arm_instruction


class SourceRange(TypedDict):
    line: int
    startCol: int
    endCol: int
    path: NotRequired[str]


class Diagnostic(SourceRange):
    severity: Literal["error", "warning"]
    code: str
    message: str


class SourceSymbol(SourceRange):
    name: str
    kind: Literal["section", "variable", "label"]


class AnalysisResult(TypedDict):
    diagnostics: list[Diagnostic]
    definitions: list[SourceSymbol]
    symbols: list[SourceSymbol]
    dependencies: list[str]


def _source_range(line: int, raw: str, token: str | None = None) -> SourceRange:
    text = raw[: find_comment_start(raw)].rstrip("\r\n")
    token = token or text.strip()
    start = text.casefold().find(token.casefold())
    if start < 0:
        token = text.strip()
        start = text.find(token)
    return {"line": line, "startCol": start, "endCol": start + max(len(token), 1)}


def _diagnostic(
    line: int, raw: str, message: str, *, token: str | None = None, code: str = "instruction"
) -> Diagnostic:
    return {
        **_source_range(line, raw, token),
        "severity": "error",
        "code": code,
        "message": message,
    }


def _source_symbol(entry: SourceEntry) -> SourceSymbol | None:
    kind: Literal["section", "variable", "label"]
    if entry.kind == "section":
        name, kind = "space", "section"
    elif entry.kind == "label":
        name = entry.label
        kind = "section" if name.casefold() == "main" else "label"
    elif entry.kind == "data":
        separator = "=" if "=" in entry.stripped else ":"
        if separator not in entry.stripped:
            return None
        name = entry.stripped.split(separator, 1)[0].strip()
        kind = "variable"
    else:
        return None
    return {"name": name, "kind": kind, **_source_range(entry.line, entry.raw, name)}


def analyze_text(
    text: str,
    source_path: Path | None = None,
    *,
    documents: Mapping[Path, str] | None = None,
) -> AnalysisResult:
    source_path = source_path.resolve() if source_path is not None else None
    diagnostics: list[Diagnostic] = []

    def locate(item: SourceRange, origin: SourceLine) -> None:
        item["line"] = origin.line
        if origin.path is not None:
            item["path"] = str(origin.path)

    def report_include(origin: SourceLine, error: DirectiveError) -> None:
        diagnostic = _diagnostic(origin.line, origin.raw, str(error), code="include")
        locate(diagnostic, origin)
        diagnostics.append(diagnostic)

    expanded = expand_source(
        text.splitlines(), source_path.parent if source_path else None,
        source_path=source_path, documents=documents, on_error=report_include,
    )
    lines = [origin.raw for origin in expanded.lines]
    source_diagnostics: list[Diagnostic] = []

    def report_constant(line: int, error: DirectiveError) -> None:
        message = str(error).removesuffix(f" (line {line + 1})")
        source_diagnostics.append(_diagnostic(line, lines[line], message, code="constant"))

    def report_source(error: SourceError) -> None:
        source_diagnostics.append(
            _diagnostic(
                error.entry.line, error.entry.raw, str(error), token=error.token, code=error.code
            )
        )

    _, constants = extract_constants(lines, on_error=report_constant)
    layout = layout_source(
        lines, {**NPU_BUILTIN_CONSTANTS, **constants}, on_error=report_source,
        require_instructions=False,
    )
    data_only = bool(layout.entries) and all(
        entry.kind in {"section", "data"} for entry in layout.entries
    )
    if not data_only and not any(entry.kind == "instruction" for entry in layout.entries):
        anchor = next((entry for entry in layout.entries if entry.kind == "label"), None)
        source_diagnostics.append(_diagnostic(
            anchor.line if anchor else 0, anchor.raw if anchor else "",
            "Program contains no instructions; no instructions encoded.", code="no-instructions",
        ))
    invalid_instructions = {
        diagnostic["line"] for diagnostic in source_diagnostics
        if diagnostic["code"] == "instruction"
    }
    for entry in layout.entries:
        if entry.kind != "instruction" or entry.line in invalid_instructions:
            continue
        try:
            encode_asm(
                [normalize_arm_instruction(entry.stripped)], layout.symbols, layout.data.matrices
            )
        except ValueError as exc:
            source_diagnostics.append(_diagnostic(entry.line, entry.raw, str(exc)))

    definitions: list[SourceSymbol] = []
    for entry in layout.entries:
        symbol = _source_symbol(entry)
        if symbol is not None:
            locate(symbol, expanded.lines[entry.line])
            definitions.append(symbol)
    for diagnostic in source_diagnostics:
        if expanded.lines:
            locate(diagnostic, expanded.lines[diagnostic["line"]])
        diagnostics.append(diagnostic)
    diagnostics.sort(key=lambda item: (item.get("path", ""), item["line"], item["startCol"]))
    return {
        "diagnostics": diagnostics,
        "definitions": definitions,
        "symbols": [symbol for symbol in definitions if symbol.get("path") == (
            str(source_path) if source_path else None
        )],
        "dependencies": sorted(str(path) for path in expanded.dependencies),
    }


def _file_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value or "://" in value:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else None


def main() -> int:
    try:
        payload: object = json.load(sys.stdin)
        if not isinstance(payload, dict) or not isinstance(payload.get("text", ""), str):
            raise ValueError("expected an object with a string 'text' field")
        raw_documents = payload.get("documents", {})
        if not isinstance(raw_documents, dict):
            raise ValueError("expected 'documents' to map absolute paths to source text")
        documents: dict[Path, str] = {}
        for key, value in raw_documents.items():
            path = _file_path(key)
            if path is None or not isinstance(value, str):
                raise ValueError("expected 'documents' to map absolute paths to source text")
            documents[path] = value
        result = analyze_text(
            payload.get("text", ""), _file_path(payload.get("path")), documents=documents
        )
    except ValueError as exc:
        json.dump(
            {
                "diagnostics": [
                    _diagnostic(0, "", f"Invalid analyzer payload: {exc}", code="json")
                ],
                "definitions": [],
                "symbols": [],
                "dependencies": [],
            },
            sys.stdout,
        )
        return 1
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
