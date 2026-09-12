"""Turn the host keyboard into the board's KEY[3:0], over the JTAG cable.

The FPGA side is the altsource_probe instance in hdl/CPU.sv, whose source
register is OR-ed into the MMIO KEYS slot.  Nothing here touches the HPS, and no
PS/2 or USB keyboard is involved: keystrokes travel down the same USB-Blaster
connection that programs the board.

    python scripts/board/jtag_keys.py                # 1-4 drive KEY0-KEY3
    python scripts/board/jtag_keys.py --preset doom  # WASD, f fires
    python scripts/board/jtag_keys.py --type         # type at programs/tinyml_text.de1

A binding can drive several keys at once, which matters because programs read
the whole mask: programs/doom.de1 turns FIRE into the KEY1+KEY2 chord, and no
single-bit binding could reach it.

--type is a different shape of driver.  programs/tinyml_text.de1 has no text
input: it draws a 32-key grid that four buttons walk, so one letter is a whole
sequence of presses.  That mode tracks the highlighted key and emits the walk,
turning the host keyboard into the board's, at the cost of assuming it knows
where the cursor is -- see --cursor.

On Windows the keyboard's live state is read directly, so a held key is a held
button and movement is continuous; the trade is that keys register whatever
window has focus.  --pulse instead sends each press typed into this window as a
fixed-length --hold pulse, and --toggle latches each bit until the key is
pressed again, which suits mode switches better than momentary buttons.

Requires quartus_stp on PATH or QUARTUS_ROOTDIR set.  The Programmer and
SignalTap cannot hold the JTAG cable at the same time as this script.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parents[2]
TCL_SCRIPT = ROOT / "scripts" / "board" / "jtag_keys.tcl"

KEY_COUNT = 4
DEFAULT_KEYMAP = "1234"

REPLY_MARKER = "@@"  # marks jtag_keys.tcl replies

NAMED_CHARACTERS = {"space": " ", "comma": ","}

PRESETS = {
    "doom": "a=0,w=1,s=2,d=3,f=12,space=12",
}

TEXT_KEY_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ., "
TEXT_COLUMNS = 8
TEXT_KEYS = 32
TEXT_SPACE = TEXT_KEY_CHARS.index(" ")
TEXT_BACKSPACE, TEXT_CLEAR, TEXT_GO = 29, 30, 31
TEXT_LEFT, TEXT_ROW, TEXT_SELECT, TEXT_RIGHT = 1, 2, 4, 8
TEXT_QUIT_KEYS = frozenset({"\x03", "\x04", "\x1b"})
TEXT_GENERATE_SETTLE = 0.5  # seconds to wait out a generation

QUIT_KEYS = frozenset({"q", "Q", "\x03", "\x04", "\x1b"})
DEFAULT_HOLD_MS = 80
POLL_SECONDS = 0.005


class SessionError(RuntimeError):
    pass


class KeymapError(ValueError):
    pass


def parse_keymap(spec: str) -> dict[str, int]:
    spec = spec.strip()
    if not spec:
        raise KeymapError("empty key map")

    if "=" not in spec:
        if len(spec) > KEY_COUNT:
            raise KeymapError(
                f"positional map has {len(spec)} characters but there are "
                f"only {KEY_COUNT} keys"
            )
        if len(set(spec)) != len(spec):
            raise KeymapError("positional map repeats a character")
        return {char: 1 << index for index, char in enumerate(spec)}

    bindings: dict[str, int] = {}
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        char_part, separator, keys_part = entry.partition("=")
        if not separator:
            raise KeymapError(f"'{entry}' is missing '='")

        char = NAMED_CHARACTERS.get(char_part.strip().lower(), char_part)
        if len(char) != 1:
            raise KeymapError(
                f"'{char_part}' is not a single character "
                f"(names: {', '.join(sorted(NAMED_CHARACTERS))})"
            )
        if char in bindings:
            raise KeymapError(f"'{char_part}' is bound twice")

        keys_part = keys_part.strip()
        if not keys_part:
            raise KeymapError(f"'{entry}' binds no key")

        mask = 0
        for digit in keys_part:
            if not digit.isdigit() or int(digit) >= KEY_COUNT:
                raise KeymapError(
                    f"'{digit}' is not a key index 0..{KEY_COUNT - 1} in '{entry}'"
                )
            mask |= 1 << int(digit)
        bindings[char] = mask

    if not bindings:
        raise KeymapError("empty key map")
    return bindings


def resolve_binding(char: str, bindings: dict[str, int]) -> int | None:
    if char in bindings:
        return bindings[char]
    return bindings.get(char.lower())


def describe_keymap(bindings: dict[str, int]) -> str:
    def render_char(char: str) -> str:
        for name, value in NAMED_CHARACTERS.items():
            if value == char:
                return name
        return char

    return "  ".join(
        f"{render_char(char)} -> "
        + "+".join(f"KEY{bit}" for bit in range(KEY_COUNT) if mask & (1 << bit))
        for char, mask in bindings.items()
    )


def text_key_name(index: int) -> str:
    if not 0 <= index < TEXT_KEYS:
        raise KeymapError(f"key index {index} is outside the {TEXT_KEYS}-key grid")
    if index == TEXT_SPACE:
        return "SP"
    if index < len(TEXT_KEY_CHARS):
        return TEXT_KEY_CHARS[index]
    return {TEXT_BACKSPACE: "<", TEXT_CLEAR: "CL", TEXT_GO: "GO"}[index]


def text_target(char: str) -> int | None:
    if char in ("\r", "\n"):
        return TEXT_GO
    if char in ("\x08", "\x7f"):
        return TEXT_BACKSPACE
    if char == "\x15":
        return TEXT_CLEAR
    index = TEXT_KEY_CHARS.find(char.upper())
    return index if index >= 0 else None


def parse_cursor(spec: str) -> int:
    if len(spec) == 1:
        index = TEXT_KEY_CHARS.find(spec.upper())
        if index >= 0:
            return index
    named = {"sp": TEXT_SPACE, "bs": TEXT_BACKSPACE, "cl": TEXT_CLEAR, "go": TEXT_GO}
    if spec.strip().lower() in named:
        return named[spec.strip().lower()]
    raise KeymapError(
        f"{spec!r} is not a key on the grid; pass a letter, '.', ',', or SP/BS/CL/GO"
    )


def text_key_sequence(target: int, selected: int) -> list[int]:
    for value in (target, selected):
        if not 0 <= value < TEXT_KEYS:
            raise KeymapError(f"key index {value} is outside the {TEXT_KEYS}-key grid")
    rows = (target // TEXT_COLUMNS - selected // TEXT_COLUMNS) % (TEXT_KEYS // TEXT_COLUMNS)
    right = (target % TEXT_COLUMNS - selected % TEXT_COLUMNS) % TEXT_COLUMNS
    columns = (
        [TEXT_RIGHT] * right
        if right <= TEXT_COLUMNS - right
        else [TEXT_LEFT] * (TEXT_COLUMNS - right)
    )
    return [TEXT_ROW] * rows + columns + [TEXT_SELECT]


def _find_quartus_stp(explicit: str | None) -> str:
    if explicit:
        if not Path(explicit).is_file():
            raise SessionError(f"quartus_stp not found at {explicit}")
        return explicit

    found = shutil.which("quartus_stp")
    if found:
        return found

    rootdir = os.environ.get("QUARTUS_ROOTDIR")
    if rootdir:
        for subdir in ("bin64", "bin"):
            for name in ("quartus_stp.exe", "quartus_stp"):
                candidate = Path(rootdir) / subdir / name
                if candidate.is_file():
                    return str(candidate)

    raise SessionError(
        "quartus_stp not on PATH and QUARTUS_ROOTDIR is unset or does not "
        "contain it; pass --quartus-stp with the full path"
    )


class JtagKeySession:
    def __init__(
        self,
        *,
        quartus_stp: str,
        instance: int = 0,
        hardware: str | None = None,
        startup_timeout: float = 120.0,
    ) -> None:
        self._quartus_stp = quartus_stp
        self._instance = instance
        self._hardware = hardware
        self._startup_timeout = startup_timeout
        self._process: subprocess.Popen[bytes] | None = None
        self._connection: socket.socket | None = None
        self._reader: IO[str] | None = None
        self._writer: IO[str] | None = None
        self._log_path: Path | None = None
        self.device = ""

    def __enter__(self) -> JtagKeySession:
        listener = socket.socket()
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(0.25)
            port = listener.getsockname()[1]

            handle, log_name = tempfile.mkstemp(prefix="jtag_keys_", suffix=".log")
            self._log_path = Path(log_name)
            command = [
                self._quartus_stp, "-t", str(TCL_SCRIPT),
                "-port", str(port), "-instance", str(self._instance),
            ]
            if self._hardware:
                command += ["-hardware", self._hardware]

            try:
                with os.fdopen(handle, "wb") as log:
                    self._process = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        cwd=str(ROOT),
                    )
            except OSError as error:
                raise SessionError(
                    self._failure(f"could not run {self._quartus_stp}: {error}")
                ) from None

            deadline = time.monotonic() + self._startup_timeout
            connection = None
            while connection is None:
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    status = self._process.poll()
                    if status is not None:
                        raise SessionError(
                            self._failure(
                                f"quartus_stp exited with status {status} "
                                f"before opening the session"
                            )
                        ) from None
                    if time.monotonic() >= deadline:
                        raise SessionError(
                            self._failure(
                                f"quartus_stp did not connect back within "
                                f"{self._startup_timeout:.0f}s"
                            )
                        ) from None
        finally:
            listener.close()

        self._connection = connection
        self._reader = connection.makefile("r", encoding="ascii", newline="\n")
        self._writer = connection.makefile("w", encoding="ascii", newline="\n")

        reply = self._read_reply()
        if reply.startswith("FATAL"):
            raise SessionError(self._failure(reply[5:].strip()))
        if not reply.startswith("READY"):
            raise SessionError(f"unexpected greeting from quartus_stp: {reply!r}")
        self.device = reply.split(" ", 1)[1] if " " in reply else "?"
        return self

    def _failure(self, reason: str) -> str:
        process = self._process
        if process is not None and process.poll() is None:
            process.kill()
        detail = ""
        if self._log_path is not None and self._log_path.is_file():
            noise = ("Info:", "Warning:", "TBBmalloc")
            lines = [
                line.strip()
                for line in self._log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if line.strip() and not line.strip().startswith(noise)
            ]
            if lines:
                detail = "\n  " + "\n  ".join(lines[-5:])
            detail += f"\n  (full log: {self._log_path})"
        return reason + detail

    def __exit__(self, *_exc: object) -> bool:
        process = self._process
        try:
            if self._writer is not None:
                self._send("SET 0")
                self._send("QUIT")
            if process is not None:
                process.wait(timeout=10)
        except (SessionError, OSError, ValueError, subprocess.TimeoutExpired):
            if process is not None:
                process.kill()
        finally:
            for stream in (self._reader, self._writer):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()
            if self._connection is not None:
                self._connection.close()
            if self._log_path is not None and self._log_path.is_file():
                self._log_path.unlink(missing_ok=True)
            self._process = None
            self._reader = self._writer = None
            self._connection = None
        return False

    def _read_reply(self) -> str:
        reader = self._reader
        if reader is None:
            raise SessionError("session is closed")
        while True:
            line = reader.readline()
            if not line:
                raise SessionError(
                    self._failure("quartus_stp closed the connection")
                )
            line = line.strip()
            if line.startswith(REPLY_MARKER):
                return line[len(REPLY_MARKER):].strip()

    def _send(self, command: str) -> str:
        writer = self._writer
        if writer is None:
            raise SessionError("session is closed")
        writer.write(command + "\n")
        writer.flush()
        reply = self._read_reply()
        if reply.startswith("ERR"):
            raise SessionError(reply[3:].strip())
        return reply

    def set_mask(self, mask: int) -> None:
        self._send(f"SET {mask & 0xF}")


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    _user32.VkKeyScanW.restype = ctypes.c_short
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short

    VK_ESCAPE = 0x1B

    class KeyStatePoller:
        def __init__(self, characters: str) -> None:
            self._codes: dict[str, int] = {}
            for char in characters:
                scan = _user32.VkKeyScanW(char)
                if scan == -1:
                    continue
                self._codes[char] = scan & 0xFF

            self._quit_codes = [VK_ESCAPE]
            quit_scan = _user32.VkKeyScanW("q")
            if "q" not in self._codes and quit_scan != -1:
                self._quit_codes.append(quit_scan & 0xFF)

        @property
        def usable(self) -> bool:
            return bool(self._codes)

        @property
        def quit_hint(self) -> str:
            return "q or Esc" if len(self._quit_codes) > 1 else "Esc"

        def _down(self, code: int) -> bool:
            return bool(_user32.GetAsyncKeyState(code) & 0x8000)

        def held(self) -> set[str]:
            return {char for char, code in self._codes.items() if self._down(code)}

        def quit_requested(self) -> bool:
            return any(self._down(code) for code in self._quit_codes)

    import msvcrt

    class KeyReader:
        def __enter__(self) -> KeyReader:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def poll(self) -> str | None:
            if not msvcrt.kbhit():
                return None
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                msvcrt.getwch()
                return None
            return char

else:
    import select
    import termios
    import tty

    class KeyReader:
        def __init__(self) -> None:
            self._fd = sys.stdin.fileno()
            self._saved: list | None = None

        def __enter__(self) -> KeyReader:
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            return self

        def __exit__(self, *_exc: object) -> bool:
            if self._saved is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            return False

        def poll(self) -> str | None:
            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1)
            return None


def _render(mask: int) -> str:
    keys = " ".join(
        f"[{bit}]" if mask & (1 << bit) else f" {bit} " for bit in range(KEY_COUNT)
    )
    return f"\rKEY {keys}   mask=0x{mask:X}  "


def _run_held(
    session: JtagKeySession,
    bindings: dict[str, int],
    poller: KeyStatePoller,
    reader: KeyReader,
) -> None:
    written = -1
    while True:
        while reader.poll() is not None:
            pass

        if poller.quit_requested():
            break
        mask = 0
        for char in poller.held():
            mask |= bindings[char]
        if mask != written:
            session.set_mask(mask)
            written = mask
            sys.stdout.write(_render(mask))
            sys.stdout.flush()
        time.sleep(POLL_SECONDS)


def _run_pulsed(
    session: JtagKeySession,
    bindings: dict[str, int],
    reader: KeyReader,
    hold_seconds: float,
    toggle: bool,
) -> None:
    expiry: dict[int, float] = {}
    latched = 0
    written = -1

    while True:
        char = reader.poll()
        if char is not None:
            pressed = resolve_binding(char, bindings)
            if pressed is None:
                if char in QUIT_KEYS:
                    break
            elif toggle:
                latched ^= pressed
            else:
                expiry[pressed] = time.monotonic() + hold_seconds

        now = time.monotonic()
        mask = latched
        for pressed, deadline in expiry.items():
            if now < deadline:
                mask |= pressed

        if mask != written:
            session.set_mask(mask)
            written = mask
            sys.stdout.write(_render(mask))
            sys.stdout.flush()

        time.sleep(POLL_SECONDS)


def _run_text(
    session: JtagKeySession,
    reader: KeyReader,
    hold_seconds: float,
    cursor: int,
) -> None:
    def press(mask: int) -> None:
        session.set_mask(mask)
        time.sleep(hold_seconds)
        session.set_mask(0)
        time.sleep(hold_seconds)

    while True:
        char = reader.poll()
        if char is None:
            time.sleep(POLL_SECONDS)
            continue
        if char in TEXT_QUIT_KEYS:
            break
        target = text_target(char)
        if target is None:
            continue
        for mask in text_key_sequence(target, cursor):
            press(mask)
        cursor = target
        if target == TEXT_GO:
            sys.stdout.write("  [GO]\n")
            sys.stdout.flush()
            time.sleep(TEXT_GENERATE_SETTLE)
            continue
        if target == TEXT_CLEAR:
            sys.stdout.write("  [CL]\n")
        elif target == TEXT_BACKSPACE:
            sys.stdout.write("\b \b")
        else:
            sys.stdout.write(" " if target == TEXT_SPACE else TEXT_KEY_CHARS[target])
        sys.stdout.flush()


def run(
    *,
    quartus_stp: str,
    bindings: dict[str, int],
    hold_seconds: float,
    toggle: bool,
    instance: int,
    hardware: str | None,
    pulse: bool = False,
    text: bool = False,
    cursor: int = 0,
) -> int:
    poller = None
    if not text and not pulse and not toggle and os.name == "nt":
        candidate = KeyStatePoller("".join(bindings))
        if candidate.usable:
            poller = candidate

    with JtagKeySession(
        quartus_stp=quartus_stp, instance=instance, hardware=hardware
    ) as session, KeyReader() as reader:
        print(f"Connected to {session.device}.")
        if text:
            print("  mode: type    letters, '.', ',' and space reach the grid;")
            print("        Enter selects GO, Backspace deletes, Ctrl-U clears.")
            print(f"  the highlighted key is assumed to be {text_key_name(cursor)}; "
                  "after using the board's own buttons, restart with --cursor.")
            print("  Esc to quit.\n")
            _run_text(session, reader, hold_seconds, cursor)
            print("\nSession closed.")
            return 0
        print(f"  {describe_keymap(bindings)}")
        if poller is not None:
            print("  mode: held    keys register while this runs, in any window.")
            print(f"  {poller.quit_hint} to quit.\n")
            _run_held(session, bindings, poller, reader)
        else:
            mode = "toggle" if toggle else "pulse"
            quit_hint = "Esc" if resolve_binding("q", bindings) is not None else "q or Esc"
            print(f"  mode: {mode}   type into this window.  {quit_hint} to quit.\n")
            _run_pulsed(session, bindings, reader, hold_seconds, toggle)

    print("\nSession closed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--quartus-stp",
        help="full path to quartus_stp (default: PATH, then QUARTUS_ROOTDIR)",
    )
    parser.add_argument(
        "--map",
        dest="keymap",
        help=(
            "either one character per KEY low bit first (e.g. 1234), or "
            "explicit bindings that may cover several keys (e.g. "
            f"a=0,w=1,f=12).  Default: {DEFAULT_KEYMAP}"
        ),
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        help="a program's control scheme: " + "; ".join(
            f"{name} = {spec}" for name, spec in sorted(PRESETS.items())
        ),
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=DEFAULT_HOLD_MS,
        help=f"pulse length in ms (default: {DEFAULT_HOLD_MS})",
    )
    parser.add_argument(
        "--toggle",
        action="store_true",
        help="latch each bit until its key is pressed again",
    )
    parser.add_argument(
        "--pulse",
        action="store_true",
        help=(
            "send each press as a fixed-length pulse from characters typed into "
            "this window, instead of mirroring the keyboard's live state"
        ),
    )
    parser.add_argument(
        "--type",
        dest="text",
        action="store_true",
        help=(
            "drive the on-screen keyboard of programs/tinyml_text.de1: each "
            "typed character becomes the walk that highlights and selects its "
            "grid key, Enter selects GO"
        ),
    )
    parser.add_argument(
        "--cursor",
        default="A",
        help=(
            "with --type, the grid key the program is currently highlighting "
            "(default: A, which is where it starts). Accepts a grid character "
            "or SP/BS/CL/GO"
        ),
    )
    parser.add_argument(
        "--instance",
        type=int,
        default=0,
        help="altsource_probe instance index (default: 0)",
    )
    parser.add_argument(
        "--hardware",
        help="substring selecting the programming cable when several are present",
    )
    args = parser.parse_args(argv)

    if args.keymap is not None and args.preset:
        parser.error("--map and --preset set the same thing; pass only one")
    if args.text:
        for name, value in (
            ("--map", args.keymap is not None),
            ("--preset", bool(args.preset)),
            ("--toggle", args.toggle),
            ("--pulse", args.pulse),
        ):
            if value:
                parser.error(f"--type drives the on-screen keyboard itself; drop {name}")
    elif args.cursor != "A":
        parser.error("--cursor only means something with --type")

    cursor = 0
    if args.text:
        try:
            cursor = parse_cursor(args.cursor)
        except KeymapError as error:
            parser.error(f"--cursor: {error}")

    if args.keymap is not None:
        spec = args.keymap
    elif args.preset:
        spec = PRESETS[args.preset]
    else:
        spec = DEFAULT_KEYMAP

    try:
        bindings = parse_keymap(spec)
    except KeymapError as error:
        parser.error(f"--map: {error}")

    try:
        quartus_stp = _find_quartus_stp(args.quartus_stp)
        return run(
            quartus_stp=quartus_stp,
            bindings=bindings,
            hold_seconds=args.hold / 1000.0,
            toggle=args.toggle,
            instance=args.instance,
            hardware=args.hardware,
            pulse=args.pulse,
            text=args.text,
            cursor=cursor,
        )
    except SessionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
