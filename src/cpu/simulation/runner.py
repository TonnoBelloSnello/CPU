from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Full, Queue
from time import monotonic

from ..encoder.assemble import assemble
from .parser import SnapshotParser
from .rtl_config import (
    HDL_DIR,
    LOADER_MAX_PROGRAM_SIZE,
    RAM_ADDR_WIDTH,
    VGA_FB_HEIGHT,
    VGA_FB_WIDTH,
)
from .snapshot import Snapshot, SnapshotEvent, StreamEvent
from .templates import (
    SIMULATION_TIMEOUT_MARKER,
    render_loader_sv,
    render_runtime_loader_sv,
    render_runtime_testbench,
)

DEFAULT_ADDR_WIDTH = RAM_ADDR_WIDTH
DEFAULT_DATA_WIDTH = 8
DEFAULT_MAX_CYCLES = 1_100_000_000
DEFAULT_VGA_WIDTH = VGA_FB_WIDTH
DEFAULT_VGA_HEIGHT = VGA_FB_HEIGHT
MAX_CAPTURED_LOG_LINES = 2_000
MAX_CAPTURED_LOG_LINE_LENGTH = 4_096
MAX_STREAM_LOG_EVENTS = 2_000
MAX_STREAM_PIXEL_BATCH = 256
PIXEL_RE = re.compile(r"PIXEL:\s*x=(\d+)\s+y=(\d+)\s+color=(\d+)\s+addr=(\d+)")
NOISY_LOG_PREFIXES = (
    "BRANCH: Jumping to address",
    "Condition not met (cond=",
)
_CACHE_SCHEMA = b"cpu-runtime-harness-v1"
_CACHE_EXECUTABLE_NAME = "cpu_runtime.vvp"
_CACHE_BUILD_LOCK = threading.Lock()


class SimulationError(RuntimeError):
    pass


def _run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        combined = (result.stdout or "") + (result.stderr or "")
        raise SimulationError(f"Command failed: {' '.join(args)}\n{combined}")
    return result


_CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@contextmanager
def _compiled_icarus_workspace(
    program_bytes: bytes,
    *,
    executable_name: str,
    defines: tuple[str, ...] = ("SIMULATION",),
    top_module: str | None = None,
    testbench_name: str | None = None,
    testbench_text: str | None = None,
    loader_text: str | None = None,
    command_runner: _CommandRunner | None = None,
) -> Iterator[tuple[Path, Path]]:
    if (testbench_name is None) != (testbench_text is None):
        raise ValueError("testbench_name and testbench_text must be provided together")
    if command_runner is None:
        command_runner = _run_command

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        modules_dst = tmp_path / "modules"
        shutil.copytree(HDL_DIR, modules_dst)

        pkg_path = modules_dst / "cpu_pkg.sv"
        pkg_text = pkg_path.read_text(encoding="utf-8")
        pkg_text = re.sub(
            r"(localparam\s+int\s+USE_INIT_FILE\s*=\s*)\d+",
            r"\g<1>0",
            pkg_text,
        )
        pkg_path.write_text(pkg_text, encoding="utf-8")

        loader_path = modules_dst / "loader.sv"
        loader_path.write_text(
            loader_text if loader_text is not None else render_loader_sv(program_bytes),
            encoding="ascii",
        )

        testbench_path: Path | None = None
        if testbench_name is not None and testbench_text is not None:
            testbench_path = tmp_path / testbench_name
            testbench_path.write_text(testbench_text, encoding="ascii")

        all_sv = sorted(modules_dst.glob("*.sv"))
        sv_files = [p for p in all_sv if "_pkg" in p.name]
        sv_files += [p for p in all_sv if "_pkg" not in p.name]
        output_path = tmp_path / executable_name

        compile_args = [
            "iverilog", "-g2012", "-I", str(modules_dst),
            *(f"-D{name}" for name in defines),
        ]
        if top_module is not None:
            compile_args.extend(["-s", top_module])
        compile_args.extend(["-o", str(output_path), *(str(path) for path in sv_files)])
        if testbench_path is not None:
            compile_args.append(str(testbench_path))
        command_runner(compile_args, tmp_path)

        yield tmp_path, output_path


def _simulation_cache_root() -> Path:
    configured = os.environ.get("CPU_SIM_CACHE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "cpu-web-simulation-cache"


def _compiler_fingerprint() -> bytes:
    fingerprint = bytearray()
    for tool_name in ("iverilog", "vvp"):
        tool = shutil.which(tool_name)
        if tool is None:
            raise SimulationError(f"{tool_name} not available on PATH")
        tool_path = Path(tool).resolve()
        try:
            stat = tool_path.stat()
        except OSError as exc:
            raise SimulationError(f"Cannot inspect {tool_name}: {exc}") from exc
        fingerprint.extend(
            f"{tool_name}\0{tool_path}\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode(
                "utf-8", errors="surrogatepass"
            )
        )
    return bytes(fingerprint)


def _runtime_harness_sources(
    addr_width: int,
    data_width: int,
) -> tuple[str, str]:
    return (
        render_runtime_loader_sv(addr_width=addr_width),
        render_runtime_testbench("RuntimeTB", addr_width, data_width),
    )


def _runtime_cache_key(
    addr_width: int,
    data_width: int,
    defines: tuple[str, ...],
) -> str:
    digest = hashlib.sha256(_CACHE_SCHEMA)
    digest.update(_compiler_fingerprint())
    digest.update(f"\0{addr_width}\0{data_width}\0".encode("ascii"))
    for define in defines:
        digest.update(b"D\0" + define.encode("ascii") + b"\0")
    loader_text, testbench_text = _runtime_harness_sources(addr_width, data_width)
    digest.update(b"LOADER\0" + loader_text.encode("ascii"))
    digest.update(b"TESTBENCH\0" + testbench_text.encode("ascii"))
    rtl_sources = [*HDL_DIR.glob("*.sv"), *HDL_DIR.glob("*.svh")]
    for path in sorted(rtl_sources, key=lambda item: item.name):
        digest.update(b"FILE\0" + path.name.encode("utf-8") + b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError as exc:
            raise SimulationError(f"Cannot read RTL source {path}: {exc}") from exc
    return digest.hexdigest()


def _cached_runtime_executable(
    *,
    addr_width: int,
    data_width: int,
    fast: bool,
) -> Path:
    defines = ("SIMULATION", "SNAPSHOT_MODE")
    if fast:
        defines += ("WEB_FAST_SIMULATION",)
    cache_key = _runtime_cache_key(addr_width, data_width, defines)
    cache_root = _simulation_cache_root()
    cache_dir = cache_root / cache_key
    executable = cache_dir / _CACHE_EXECUTABLE_NAME
    if executable.is_file():
        return executable

    with _CACHE_BUILD_LOCK:
        if executable.is_file():
            return executable
        try:
            cache_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SimulationError(f"Cannot create simulator cache: {exc}") from exc

        loader_text, testbench_text = _runtime_harness_sources(addr_width, data_width)
        try:
            staging_path: Path | None = Path(
                tempfile.mkdtemp(prefix=f".{cache_key[:12]}-", dir=str(cache_root))
            )
        except OSError as exc:
            raise SimulationError(
                f"Cannot create simulator cache staging directory: {exc}"
            ) from exc
        try:
            with _compiled_icarus_workspace(
                b"",
                executable_name=_CACHE_EXECUTABLE_NAME,
                defines=defines,
                top_module="RuntimeTB",
                testbench_name="runtime_tb.sv",
                testbench_text=testbench_text,
                loader_text=loader_text,
            ) as (_, built_executable):
                shutil.copy2(built_executable, staging_path / _CACHE_EXECUTABLE_NAME)

            try:
                staging_path.replace(cache_dir)
                staging_path = None
            except OSError:
                if not executable.is_file():
                    raise
        except SimulationError:
            raise
        except OSError as exc:
            raise SimulationError(f"Cannot publish simulator cache: {exc}") from exc
        finally:
            if staging_path is not None and staging_path.exists():
                shutil.rmtree(staging_path, ignore_errors=True)

    if not executable.is_file():
        raise SimulationError("Compiled simulator cache artifact is missing")
    return executable


def prepare_simulation_cache(
    *,
    addr_width: int = DEFAULT_ADDR_WIDTH,
    data_width: int = DEFAULT_DATA_WIDTH,
    fast: bool = True,
) -> Path:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        raise SimulationError("iverilog/vvp not available on PATH")
    return _cached_runtime_executable(
        addr_width=addr_width,
        data_width=data_width,
        fast=fast,
    )


@contextmanager
def _cached_icarus_run_workspace(
    program_bytes: bytes,
    *,
    addr_width: int,
    data_width: int,
    fast: bool,
) -> Iterator[tuple[Path, Path]]:
    executable = _cached_runtime_executable(
        addr_width=addr_width,
        data_width=data_width,
        fast=fast,
    )
    try:
        run_workspace = tempfile.TemporaryDirectory(prefix="cpu-simulation-run-")
    except OSError as exc:
        raise SimulationError(f"Cannot create simulator run directory: {exc}") from exc
    with run_workspace as tmpdir:
        tmp_path = Path(tmpdir)
        try:
            (tmp_path / "program.hex").write_text(
                "".join(f"{value:02X}\n" for value in program_bytes),
                encoding="ascii",
            )
        except OSError as exc:
            raise SimulationError(f"Cannot write runtime program image: {exc}") from exc
        yield tmp_path, executable


def _runtime_plusargs(
    program_size: int,
    mem_start: int,
    mem_end: int,
    key_mask: int,
    max_cycles: int,
) -> tuple[str, ...]:
    return (
        f"+PROGRAM_SIZE={program_size}",
        f"+MEM_START={mem_start}",
        f"+MEM_END={mem_end}",
        f"+KEY_MASK={key_mask}",
        f"+MAX_CYCLES={max_cycles}",
    )


def _batched_pixel_events(
    events: Generator[StreamEvent],
) -> Generator[StreamEvent]:
    pixel_batch: list[list[int]] = []
    try:
        while True:
            try:
                event = next(events)
            except StopIteration:
                break
            except Exception:
                if pixel_batch:
                    yield {"type": "pixels", "pixels": pixel_batch}
                    pixel_batch = []
                raise

            if event["type"] == "pixel":
                pixel_batch.append([event["addr"], event["color"]])
                if len(pixel_batch) >= MAX_STREAM_PIXEL_BATCH:
                    yield {"type": "pixels", "pixels": pixel_batch}
                    pixel_batch = []
                continue
            if pixel_batch:
                yield {"type": "pixels", "pixels": pixel_batch}
                pixel_batch = []
            yield event
        if pixel_batch:
            yield {"type": "pixels", "pixels": pixel_batch}
    finally:
        events.close()


def assemble_program_image(program_text: str) -> tuple[bytes, dict[str, int]]:
    return _assemble_program(program_text.splitlines())


def _prepare_run(
    program_text: str, mem_start: int, mem_end: int, key_mask: int, addr_width: int
) -> tuple[bytes, dict[str, int]]:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        raise SimulationError("iverilog/vvp not available on PATH")

    if mem_start < 0 or mem_end < 0:
        raise SimulationError("Memory range must be non-negative")
    if mem_end < mem_start:
        raise SimulationError("mem_end must be >= mem_start")
    max_addr = (1 << addr_width) - 1
    if mem_start > max_addr or mem_end > max_addr:
        raise SimulationError(f"Memory range must be within 0..{max_addr}")
    if key_mask < 0 or key_mask > 0xF:
        raise SimulationError("key_mask must be within 0..15")

    program_bytes, labels = assemble_program_image(program_text)

    address_space_size = 1 << addr_width
    program_limit = min(LOADER_MAX_PROGRAM_SIZE, address_space_size)
    if len(program_bytes) > program_limit:
        raise SimulationError(
            "Program image is too large for runtime loading: "
            f"{len(program_bytes)} bytes including the 4-byte halt word; "
            f"maximum is {program_limit} bytes "
            f"(loader capacity {LOADER_MAX_PROGRAM_SIZE}, address width {addr_width})."
        )
    return program_bytes, labels


def _assemble_program(
    lines: Sequence[str],
    *,
    require_encoded_instructions: bool = True,
) -> tuple[bytes, dict[str, int]]:
    try:
        program = assemble(lines, require_instructions=require_encoded_instructions)
        return program.to_bytes(), program.symbols
    except ValueError as exc:
        raise SimulationError(f"Assembly failed: {exc}") from exc


def _validate_max_cycles(max_cycles: int) -> None:
    if isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles <= 0:
        raise SimulationError("max_cycles must be a positive integer")


def run_program_trace(
    program_lines: Sequence[str], *, expect_halt: bool = True
) -> tuple[str, dict[str, int]]:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        raise SimulationError("iverilog/vvp not available on PATH")
    program_bytes, labels = _assemble_program(program_lines, require_encoded_instructions=False)
    with _compiled_icarus_workspace(
        program_bytes,
        executable_name="cpu",
        loader_text=render_loader_sv(
            program_bytes,
            addr_width=RAM_ADDR_WIDTH,
            emit_loader_done=True,
        ),
    ) as (workspace, executable):
        result = _run_command(["vvp", str(executable)], workspace)
    output = result.stdout + result.stderr
    if expect_halt and "Halt: Encountered null instruction" not in output:
        raise SimulationError("Simulation did not halt on a null instruction")
    return output, labels


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)
    if proc.stdout is not None:
        proc.stdout.close()


def _run_snapshot_process(
    output_path: Path,
    cwd: Path,
    *,
    addr_width: int,
    data_width: int,
    max_cycles: int,
    vvp_args: tuple[str, ...] = (),
) -> tuple[SnapshotParser, str]:
    proc: subprocess.Popen[str] | None = None
    parser = SnapshotParser(addr_width, data_width)
    log_lines: deque[str] = deque(maxlen=MAX_CAPTURED_LOG_LINES)
    timed_out = False
    try:
        proc = subprocess.Popen(
            ["vvp", str(output_path), *vvp_args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            if SIMULATION_TIMEOUT_MARKER in raw_line:
                timed_out = True
            line = parser.feed_line(raw_line)
            if line is not None:
                log_lines.append(line[:MAX_CAPTURED_LOG_LINE_LENGTH])

        return_code = proc.wait()
        if timed_out:
            raise SimulationError(
                f"Simulation exceeded max_cycles={max_cycles} without halting"
            )
        if return_code != 0:
            tail = "\n".join(log_lines)
            suffix = f"\n{tail}" if tail else ""
            raise SimulationError(f"vvp exited with code {return_code}{suffix}")
        return parser, "\n".join(log_lines).strip()
    finally:
        if proc is not None:
            _stop_process(proc)


def run_snapshot(
    program_text: str,
    mem_start: int = 0,
    mem_end: int = 255,
    key_mask: int = 0,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    addr_width: int = DEFAULT_ADDR_WIDTH,
    data_width: int = DEFAULT_DATA_WIDTH,
    *,
    fast: bool = False,
) -> Snapshot:
    _validate_max_cycles(max_cycles)
    program_bytes, labels = _prepare_run(program_text, mem_start, mem_end, key_mask, addr_width)

    vvp_args = _runtime_plusargs(
        len(program_bytes), mem_start, mem_end, key_mask, max_cycles
    )
    with _cached_icarus_run_workspace(
        program_bytes,
        addr_width=addr_width,
        data_width=data_width,
        fast=fast,
    ) as (tmp_path, output_path):
        parser, log = _run_snapshot_process(
            output_path,
            tmp_path,
            addr_width=addr_width,
            data_width=data_width,
            max_cycles=max_cycles,
            vvp_args=vvp_args,
        )

    return {
        "registers": parser.registers,
        "memory": parser.memory,
        "framebuffer": parser.framebuffer,
        "vga_width": DEFAULT_VGA_WIDTH,
        "vga_height": DEFAULT_VGA_HEIGHT,
        "labels": labels,
        "log": log,
        "mem_start": mem_start,
        "mem_end": mem_end,
    }


@contextmanager
def _running_simulator(
    args: list[str], cwd: Path, *, quiet_interval: float = 0.25
) -> Iterator[tuple[subprocess.Popen[str], Iterator[str | None]]]:
    proc = subprocess.Popen(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    stop = threading.Event()
    queue: Queue[str | None] = Queue(maxsize=1_024)

    def enqueue(item: str | None) -> None:
        while not stop.is_set():
            try:
                queue.put(item, timeout=0.1)
                return
            except Full:
                continue

    def pump() -> None:
        assert proc.stdout is not None
        try:
            for raw_line in proc.stdout:
                if stop.is_set():
                    break
                enqueue(raw_line)
        finally:
            enqueue(None)

    reader = threading.Thread(target=pump, name="vvp-output-reader", daemon=True)
    reader.start()

    def lines() -> Iterator[str | None]:
        while True:
            try:
                item = queue.get(timeout=quiet_interval)
            except Empty:
                if proc.poll() is not None and not reader.is_alive():
                    return
                yield None
                continue
            if item is None:
                return
            yield item

    try:
        yield proc, lines()
    finally:
        stop.set()
        _stop_process(proc)
        reader.join(timeout=1.0)


class _EventStream:
    def __init__(self, *, batch_pixels: bool) -> None:
        self._batch_pixels = batch_pixels
        self._framebuffer: dict[int, int] = {}
        self._batch: list[list[int]] = []
        self._logs_sent = 0
        self._suppression_reported = False
        self._last_delivery = monotonic()

    def flush_pixels(self) -> Iterator[StreamEvent]:
        if self._batch:
            batch, self._batch = self._batch, []
            self._last_delivery = monotonic()
            yield {"type": "pixels", "pixels": batch}

    def tick(self) -> Iterator[StreamEvent]:
        if self._batch:
            yield from self.flush_pixels()
        else:
            self._last_delivery = monotonic()
            yield {"type": "heartbeat"}

    def keepalive(self, interval: float = 0.25) -> Iterator[StreamEvent]:
        if monotonic() - self._last_delivery >= interval:
            self._last_delivery = monotonic()
            yield {"type": "heartbeat"}

    def pixel(self, x: int, y: int, color: int, addr: int) -> Iterator[StreamEvent]:
        if self._framebuffer.get(addr) == color:
            return
        self._framebuffer[addr] = color
        self._last_delivery = monotonic()
        if not self._batch_pixels:
            yield {"type": "pixel", "x": x, "y": y, "color": color, "addr": addr}
            return
        self._batch.append([addr, color])
        if len(self._batch) >= MAX_STREAM_PIXEL_BATCH:
            yield from self.flush_pixels()

    def log(self, line: str) -> Iterator[StreamEvent]:
        if self._logs_sent < MAX_STREAM_LOG_EVENTS:
            self._logs_sent += 1
            self._last_delivery = monotonic()
            yield {"type": "log", "line": line[:MAX_CAPTURED_LOG_LINE_LENGTH]}
        elif not self._suppression_reported:
            self._suppression_reported = True
            self._last_delivery = monotonic()
            yield {"type": "log", "line": "Further simulator log lines suppressed."}


def _final_snapshot_event(
    parser: SnapshotParser, labels: dict[str, int], mem_start: int, mem_end: int
) -> SnapshotEvent | None:
    memory, framebuffer = parser.memory, parser.framebuffer
    if not (parser.registers or memory or framebuffer):
        return None
    return {
        "type": "snapshot",
        "registers": parser.registers,
        "memory": memory,
        "framebuffer": framebuffer,
        "vga_width": DEFAULT_VGA_WIDTH,
        "vga_height": DEFAULT_VGA_HEIGHT,
        "labels": labels,
        "mem_start": mem_start,
        "mem_end": mem_end,
    }


def stream_snapshot_events(
    program_text: str,
    mem_start: int = 0,
    mem_end: int = 255,
    key_mask: int = 0,
    addr_width: int = DEFAULT_ADDR_WIDTH,
    data_width: int = DEFAULT_DATA_WIDTH,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    *,
    fast: bool = False,
) -> Generator[StreamEvent]:
    _validate_max_cycles(max_cycles)
    program_bytes, labels = _prepare_run(program_text, mem_start, mem_end, key_mask, addr_width)
    vvp_args = _runtime_plusargs(len(program_bytes), mem_start, mem_end, key_mask, max_cycles)

    yield {
        "type": "start",
        "labels": labels,
        "vga_width": DEFAULT_VGA_WIDTH,
        "vga_height": DEFAULT_VGA_HEIGHT,
    }

    with _cached_icarus_run_workspace(
        program_bytes, addr_width=addr_width, data_width=data_width, fast=fast
    ) as (tmp_path, output_path):
        parser = SnapshotParser(addr_width, data_width, latest_sections=True)
        stream = _EventStream(batch_pixels=fast)
        timed_out = False

        with _running_simulator(["vvp", str(output_path), *vvp_args], tmp_path) as (proc, lines):
            for raw_line in lines:
                if raw_line is None:
                    yield from stream.tick()
                    continue

                yield from stream.keepalive()
                if SIMULATION_TIMEOUT_MARKER in raw_line:
                    timed_out = True
                line = parser.feed_line(raw_line)
                if line is None or SIMULATION_TIMEOUT_MARKER in line:
                    continue

                pixel_match = PIXEL_RE.search(line)
                if pixel_match:
                    x, y, color, addr = (int(value) for value in pixel_match.groups())
                    yield from stream.pixel(x, y, color, addr)
                    continue

                yield from stream.flush_pixels()
                if line.startswith(NOISY_LOG_PREFIXES) or "$finish called at" in line:
                    continue
                yield from stream.log(line)

            yield from stream.flush_pixels()
            return_code = proc.wait()
            if timed_out:
                raise SimulationError(
                    f"Simulation exceeded max_cycles={max_cycles} without halting"
                )
            if return_code != 0:
                raise SimulationError(f"vvp exited with code {return_code}")

            snapshot = _final_snapshot_event(parser, labels, mem_start, mem_end)
            if snapshot is not None:
                yield snapshot
            yield {"type": "done"}
