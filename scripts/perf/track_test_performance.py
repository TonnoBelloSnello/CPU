from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cpu.simulation.runner import run_program_trace  # noqa: E402

CLOCK_PERIOD_PS = 200
DEFAULT_HISTORY_PATH = ROOT / "scripts" / "perf" / "performance_history.jsonl"
DEFAULT_CHART_PATH = ROOT / "scripts" / "perf" / "performance_chart.svg"
NET_UNAVAILABLE = "  Net execute cycles: unavailable (missing LOADER_DONE marker)"


def _extract_cycle_metrics(verilog_output: str) -> tuple[float, float | None]:
    match = re.search(r"\$finish called at (\d+) \(1ps\)", verilog_output)
    if not match:
        raise RuntimeError("Could not find simulation finish time.")
    finish_ps = int(match.group(1))

    loader = re.search(r"LOADER_DONE at (\d+) \(1ps\)", verilog_output)
    total_cycles = finish_ps / CLOCK_PERIOD_PS
    if loader is None or int(loader.group(1)) > finish_ps:
        return total_cycles, None
    return total_cycles, (finish_ps - int(loader.group(1))) / CLOCK_PERIOD_PS


def _benchmark_result(
    benchmark_id: str,
    name: str,
    total_cycles: float,
    net_cycles: float | None,
    metrics: dict[str, int | float] | None = None,
) -> dict[str, Any]:
    return {
        "id": benchmark_id,
        "name": name,
        "total_cycles": round(total_cycles),
        "net_cycles": None if net_cycles is None else round(net_cycles),
        "metrics": metrics or {},
    }


@dataclass(frozen=True)
class _Benchmark:
    benchmark_id: str
    name: str
    title: str
    program: tuple[str, ...] = ()
    iterations: int = 0
    setup_instructions: tuple[str, ...] = ()
    loop_instructions: tuple[str, ...] = ()
    counted_ops_per_iteration: int = 1
    counted_label: str = ""

    @property
    def counted_metric_id(self) -> str:
        return self.counted_label.lower().replace(" ", "_")


BENCHMARKS: tuple[_Benchmark, ...] = (
    _Benchmark(
        benchmark_id="factorial_8",
        name="Factorial 8!",
        title="Factorial Test Performance (8!)",
        program=(
            "space:",
            "    n = 00001000",
            "main:",
            "MOV R0, [n]",
            "MOV R1, V1",
            "CMP R0, V0",
            "BEQ done",
            "MOV R2, V2",
            "outer_loop:",
            "CMP R0, R2",
            "BLT done",
            "MUL R1, R1, R2",
            "ADD R2, R2, V1",
            "B outer_loop",
            "done:",
            "MOV R6, R1",
        ),
    ),
    _Benchmark(
        benchmark_id="matrix_2x4_4x2",
        name="Matrix 2x4 x 4x2",
        title="Matrix Multiply Test Performance (2x4 * 4x2)",
        program=(
            "space:",
            "    A = {{1, 2, 3, 4}, {5, 6, 7, 8}}",
            "    B = {{8, 9}, {10, 11}, {12, 13}, {14, 15}}",
            "main:",
            "MUL R0, A, B",
            "MOV R1, [R0]",
            "ADD R0, R0, V1",
            "MOV R2, [R0]",
            "ADD R0, R0, V1",
            "MOV R3, [R0]",
            "ADD R0, R0, V1",
            "MOV R4, [R0]",
        ),
    ),
    _Benchmark(
        benchmark_id="mov_loop_200",
        name="MOV loop",
        title="MOV Amortised Performance",
        iterations=200,
        loop_instructions=("MOV R0, V1", "MOV R1, R0"),
        counted_ops_per_iteration=2,
        counted_label="MOV",
    ),
    _Benchmark(
        benchmark_id="mul_loop_200",
        name="MUL loop",
        title="Multiply Amortised Performance",
        iterations=200,
        loop_instructions=("MOV R1, v1", "MUL R0, R1, v1"),
        counted_ops_per_iteration=1,
        counted_label="MUL",
    ),
    _Benchmark(
        benchmark_id="fp_register_loop_200",
        name="FP register loop",
        title="FP Register Amortised Performance",
        iterations=200,
        setup_instructions=("FMOV R0, F1.0", "FMOV R1, F0.125", "FMOV R6, F1.0"),
        loop_instructions=("FADD R2, R0, R1", "FSUB R3, R2, R1", "FMUL R0, R3, R6"),
        counted_ops_per_iteration=3,
        counted_label="FP op",
    ),
    _Benchmark(
        benchmark_id="fp_literal_loop_120",
        name="FP literal loop",
        title="FP Literal Amortised Performance",
        iterations=120,
        setup_instructions=("FMOV R0, F1.0",),
        loop_instructions=(
            "FADD R1, R0, F0.125",
            "FSUB R2, R1, F0.125",
            "FMUL R0, R2, F1.0",
        ),
        counted_ops_per_iteration=3,
        counted_label="FP op",
    ),
    _Benchmark(
        benchmark_id="fp_divide_loop_60",
        name="FDIV loop",
        title="FDIV Amortised Performance",
        iterations=60,
        setup_instructions=("FMOV R0, F3.5", "FMOV R1, F1.25"),
        loop_instructions=("FDIV R2, R0, R1", "FDIV R3, R1, R0"),
        counted_ops_per_iteration=2,
        counted_label="FDIV",
    ),
    _Benchmark(
        benchmark_id="integer_divide_loop_60",
        name="Integer DIV loop",
        title="Integer DIV Amortised Performance",
        iterations=60,
        setup_instructions=(
            "MOV R0, V4095",
            "MUL R0, R0, V16",
            "MOV R1, V7",
            "MOV R2, V84",
        ),
        loop_instructions=("DIV R3, R0, R1", "DIV R4, R2, R1"),
        counted_ops_per_iteration=2,
        counted_label="DIV",
    ),
)


def _loop_metrics(
    spec: _Benchmark, total_cycles: float, net_cycles: float | None
) -> dict[str, int | float]:
    counted_ops = spec.iterations * spec.counted_ops_per_iteration
    instrs_per_iteration = len(spec.loop_instructions) + 3
    setup_instrs = len(spec.setup_instructions) + 1
    estimated = setup_instrs + (spec.iterations * instrs_per_iteration) + 1
    label, metric_id = spec.counted_label, spec.counted_metric_id

    metrics: dict[str, int | float] = {
        "iterations": spec.iterations,
        "estimated_dynamic_instrs": estimated,
        "total_cycles_per_iteration": total_cycles / spec.iterations,
        "total_cycles_per_estimated_instruction": total_cycles / estimated,
        f"total_cycles_per_{metric_id}": total_cycles / counted_ops,
    }
    if net_cycles is not None:
        metrics.update({
            "net_cycles_per_iteration": net_cycles / spec.iterations,
            "net_cycles_per_estimated_instruction": net_cycles / estimated,
            f"net_cycles_per_{metric_id}": net_cycles / counted_ops,
        })

    print(f"  Total cycles / iteration : {metrics['total_cycles_per_iteration']:.2f}")
    print(f"  Est. dynamic instrs      : {estimated}")
    print(f"  Total cycles / est instr : {metrics['total_cycles_per_estimated_instruction']:.2f}")
    print(f"  Total cycles / {label:<9}: {total_cycles / counted_ops:.2f} (includes loop overhead)")
    if net_cycles is None:
        print(NET_UNAVAILABLE)
    else:
        print(f"  Net execute cycles       : {net_cycles:.0f}")
        print(f"  Net cycles / iteration   : {metrics['net_cycles_per_iteration']:.2f}")
        print(f"  Net cycles / est instr   : {metrics['net_cycles_per_estimated_instruction']:.2f}")
        print(f"  Net cycles / {label:<11}: {net_cycles / counted_ops:.2f} (includes loop overhead)")

    return metrics


def run_benchmark(spec: _Benchmark) -> dict[str, Any]:
    is_loop = bool(spec.loop_instructions)
    if is_loop:
        print(f"Running {spec.name} benchmark with {spec.iterations} iterations...")
        program = [
            "space:",
            f"    iterations = {spec.iterations:08b}",
            "main:",
            *spec.setup_instructions,
            "MOV R5, [iterations]",
            "loop:",
            *spec.loop_instructions,
            "SUB R5, R5, V1",
            "CMP R5, V0",
            "BNE loop",
        ]
    else:
        program = list(spec.program)

    verilog_output, _ = run_program_trace(program)
    total_cycles, net_cycles = _extract_cycle_metrics(verilog_output)

    if is_loop:
        print(f"{spec.title} ({spec.iterations} iterations):")
        print(f"  Total clock cycles : {total_cycles:.0f}")
        metrics = _loop_metrics(spec, total_cycles, net_cycles)
    else:
        print(f"{spec.title}:")
        print(f"  Total clock cycles: {total_cycles:.0f}")
        if net_cycles is None:
            print(NET_UNAVAILABLE)
        else:
            print(f"  Net execute cycles: {net_cycles:.0f}")
        metrics = None

    return _benchmark_result(spec.benchmark_id, spec.name, total_cycles, net_cycles, metrics)


def run_benchmarks() -> list[dict[str, Any]]:
    results = []
    for index, spec in enumerate(BENCHMARKS):
        if index:
            print()
        results.append(run_benchmark(spec))
    return results


def _git_metadata() -> dict[str, Any]:
    def run_git(args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args], cwd=ROOT, text=True, capture_output=True, check=True
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip()

    return {
        "sha": run_git(["rev-parse", "--short", "HEAD"]),
        "branch": run_git(["branch", "--show-current"]),
        "dirty": bool(run_git(["status", "--short"])),
    }


def build_snapshot(results: list[dict[str, Any]], label: str | None) -> dict[str, Any]:
    now = datetime.now(UTC)
    net_values = [r["net_cycles"] for r in results if r["net_cycles"] is not None]
    total_values = [r["total_cycles"] for r in results if r["total_cycles"] is not None]

    return {
        "schema_version": 1,
        "timestamp": now.isoformat(timespec="seconds"),
        "label": label or now.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "git": _git_metadata(),
        "summary": {
            "total_cycles": sum(total_values),
            "net_cycles": sum(net_values) if net_values else None,
        },
        "benchmarks": {result["id"]: result for result in results},
    }


def append_snapshot(history_path: Path, snapshot: dict[str, Any]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True) + "\n")


def read_history(history_path: Path) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []

    snapshots: list[dict[str, Any]] = []
    text = history_path.read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON in {history_path} line {line_number}: {exc}") from exc
    return snapshots


def _format_delta(baseline: float, latest: float) -> str:
    if baseline == 0:
        return "n/a"
    delta = ((baseline - latest) / baseline) * 100.0
    return f"{'+' if delta >= 0 else ''}{delta:.2f}%"


def _svg_text(text: object) -> str:
    return html.escape(str(text), quote=True)


def _run_label(snapshot: dict[str, Any], index: int) -> str:
    return snapshot.get("label") or snapshot.get("timestamp") or f"run {index + 1}"


CHART_COLORS = (
    "#2563eb", "#dc2626", "#16a34a", "#9333ea",
    "#ea580c", "#0891b2", "#be123c", "#4d7c0f",
)


@dataclass(frozen=True, slots=True)
class _Series:
    name: str
    cycles: list[int | None]
    normalized: list[float | None]


def _collect_series(history: list[dict[str, Any]]) -> list[_Series]:
    names: dict[str, str] = {}
    for snapshot in history:
        for benchmark_id, benchmark in snapshot.get("benchmarks", {}).items():
            names[benchmark_id] = benchmark.get("name", benchmark_id)

    collected: list[_Series] = []
    for benchmark_id, name in names.items():
        cycles: list[int | None] = []
        for snapshot in history:
            benchmark = snapshot.get("benchmarks", {}).get(benchmark_id, {})
            value = benchmark.get("net_cycles")
            cycles.append(benchmark.get("total_cycles") if value is None else value)
        baseline = next((value for value in cycles if value is not None), None)
        normalized: list[float | None] = (
            [None for _ in cycles]
            if not baseline
            else [None if v is None else (v / baseline) * 100.0 for v in cycles]
        )
        collected.append(_Series(name, cycles, normalized))
    return collected


@dataclass(frozen=True, slots=True)
class _Plot:
    left: int
    top: int
    right: int
    bottom: int
    runs: int
    y_min: float
    y_max: float

    @classmethod
    def for_history(cls, runs: int, series: list[_Series], width: int) -> _Plot:
        values = [100.0] + [v for s in series for v in s.normalized if v is not None]
        low, high = min(values), max(values)
        pad = max(1.0, (high - low) * 0.2)
        y_min, y_max = low - pad, high + pad
        if y_max - y_min < 2.0:
            y_min, y_max = y_min - 1.0, y_max + 1.0
        return cls(78, 58, width - 230, 410, runs, y_min, y_max)

    def x(self, index: int) -> float:
        span = self.right - self.left
        if self.runs <= 1:
            return self.left + (span / 2)
        return self.left + (span * index / (self.runs - 1))

    def y(self, value: float) -> float:
        return self.bottom - (
            (value - self.y_min) / (self.y_max - self.y_min) * (self.bottom - self.top)
        )


def _chart_frame(plot: _Plot, width: int, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>",
        "text { font-family: Segoe UI, Arial, sans-serif; fill: #111827; }",
        ".muted { fill: #6b7280; font-size: 12px; }",
        ".axis { stroke: #9ca3af; stroke-width: 1; }",
        ".grid { stroke: #e5e7eb; stroke-width: 1; }",
        ".series { fill: none; stroke-width: 2.5; }",
        ".dot { stroke: white; stroke-width: 1.5; }",
        "</style>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{plot.left}" y="28" font-size="20" font-weight="700">CPU performance history</text>',
        f'<text x="{plot.left}" y="47" class="muted">Normalized net cycles, first recorded run = 100%. Lower is faster.</text>',
        f'<line x1="{plot.left}" y1="{plot.bottom}" x2="{plot.right}" y2="{plot.bottom}" class="axis"/>',
        f'<line x1="{plot.left}" y1="{plot.top}" x2="{plot.left}" y2="{plot.bottom}" class="axis"/>',
    ]


def _grid_and_run_ticks(plot: _Plot, history: list[dict[str, Any]]) -> Iterator[str]:
    for tick_index in range(6):
        tick = plot.y_min + ((plot.y_max - plot.y_min) * tick_index / 5)
        y = plot.y(tick)
        yield f'<line x1="{plot.left}" y1="{y:.1f}" x2="{plot.right}" y2="{y:.1f}" class="grid"/>'
        yield f'<text x="{plot.left - 10}" y="{y + 4:.1f}" text-anchor="end" class="muted">{tick:.1f}%</text>'

    for index, snapshot in enumerate(history):
        x = plot.x(index)
        yield f'<line x1="{x:.1f}" y1="{plot.bottom}" x2="{x:.1f}" y2="{plot.bottom + 5}" class="axis"/>'
        yield f'<text x="{x:.1f}" y="{plot.bottom + 22}" text-anchor="middle" class="muted">{index + 1}</text>'
        yield f'<title>Run {index + 1}: {_svg_text(_run_label(snapshot, index))}</title>'


def _legend(plot: _Plot, series: list[_Series]) -> Iterator[str]:
    legend_x = plot.right + 24
    for index, entry in enumerate(series):
        color = CHART_COLORS[index % len(CHART_COLORS)]
        y = plot.top + index * 22
        yield f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 18}" y2="{y}" stroke="{color}" stroke-width="3"/>'
        yield f'<text x="{legend_x + 25}" y="{y + 4}" class="muted">{_svg_text(entry.name)}</text>'


def _series_marks(
    plot: _Plot, series: list[_Series], history: list[dict[str, Any]]
) -> Iterator[str]:
    for color_index, entry in enumerate(series):
        color = CHART_COLORS[color_index % len(CHART_COLORS)]
        drawn = [(i, v) for i, v in enumerate(entry.normalized) if v is not None]
        if drawn:
            points = " ".join(f"{plot.x(i):.1f},{plot.y(v):.1f}" for i, v in drawn)
            yield f'<polyline points="{points}" class="series" stroke="{color}"/>'
        for index, value in drawn:
            yield f'<circle cx="{plot.x(index):.1f}" cy="{plot.y(value):.1f}" r="4.5" class="dot" fill="{color}">'
            yield (
                f"<title>{_svg_text(entry.name)} | "
                f"{_svg_text(_run_label(history[index], index))} | "
                f"{entry.cycles[index]} cycles | {value:.2f}% of baseline</title>"
            )
            yield "</circle>"


def _summary_table(plot: _Plot, series: list[_Series]) -> Iterator[str]:
    header_y = plot.bottom + 62
    yield f'<text x="{plot.left}" y="{header_y}" font-size="14" font-weight="700">Latest run vs first recorded run</text>'
    header_y += 22
    yield f'<text x="{plot.left}" y="{header_y}" class="muted">Benchmark</text>'
    yield f'<text x="{plot.left + 280}" y="{header_y}" class="muted">Latest cycles</text>'
    yield f'<text x="{plot.left + 420}" y="{header_y}" class="muted">Improvement</text>'

    for row, entry in enumerate(series, start=1):
        cycles = [value for value in entry.cycles if value is not None]
        if not cycles:
            continue
        delta = _format_delta(cycles[0], cycles[-1])
        fill = "#15803d" if delta.startswith("+") else "#b91c1c"
        y = header_y + row * 22
        yield f'<text x="{plot.left}" y="{y}" class="muted">{_svg_text(entry.name)}</text>'
        yield f'<text x="{plot.left + 280}" y="{y}" class="muted">{cycles[-1]}</text>'
        yield f'<text x="{plot.left + 420}" y="{y}" fill="{fill}" font-size="12">{delta}</text>'


def render_svg_chart(history: list[dict[str, Any]], max_runs: int) -> str:
    if max_runs > 0:
        history = history[-max_runs:]

    width = max(920, 90 * max(len(history), 1) + 260)
    series = _collect_series(history)
    plot = _Plot.for_history(len(history), series, width)

    parts = _chart_frame(plot, width, 520 + len(series) * 22)
    parts.extend(_grid_and_run_ticks(plot, history))
    parts.extend(_legend(plot, series))
    parts.extend(_series_marks(plot, series, history))
    parts.extend(_summary_table(plot, series))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_chart(history_path: Path, chart_path: Path, max_runs: int) -> None:
    history = read_history(history_path)
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_text(render_svg_chart(history, max_runs), encoding="utf-8", newline="\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CPU performance simulations and update the comparison chart."
    )
    parser.add_argument(
        "--history", "--output", dest="history", type=Path, default=DEFAULT_HISTORY_PATH,
        help="JSONL history file to append to.",
    )
    parser.add_argument(
        "--chart", type=Path, default=DEFAULT_CHART_PATH,
        help="SVG chart file to regenerate from the history.",
    )
    parser.add_argument(
        "--label", help="Human-readable label for this run. Defaults to the current timestamp."
    )
    parser.add_argument(
        "--max-chart-runs", type=int, default=40,
        help="Maximum number of most recent runs to draw in the SVG chart.",
    )
    parser.add_argument(
        "--no-record", action="store_true",
        help="Print benchmark results without appending history or regenerating the chart.",
    )
    parser.add_argument("ignored_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    results = run_benchmarks()

    if args.no_record:
        return

    append_snapshot(args.history, build_snapshot(results, args.label))
    write_chart(args.history, args.chart, args.max_chart_runs)

    print()
    print(f"Performance history appended to {args.history}")
    print(f"Performance chart written to {args.chart}")


if __name__ == "__main__":
    main()
