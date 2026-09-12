from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class RegisterValue(TypedDict):
    dec: int | None
    hex: str | None


class MemoryCell(TypedDict):
    addr: int
    dec: int | None
    hex: str | None


class SnapshotState(TypedDict):
    registers: dict[str, RegisterValue]
    memory: list[MemoryCell]
    framebuffer: list[MemoryCell]
    vga_width: int
    vga_height: int
    labels: dict[str, int]
    mem_start: int
    mem_end: int


class Snapshot(SnapshotState):
    log: str


class SnapshotEvent(SnapshotState):
    type: Literal["snapshot"]


class StartEvent(TypedDict):
    type: Literal["start"]
    labels: dict[str, int]
    vga_width: int
    vga_height: int
    engine: NotRequired[Literal["fast", "rtl"]]
    cycle_accurate: NotRequired[bool]


class PixelEvent(TypedDict):
    type: Literal["pixel"]
    x: int
    y: int
    color: int
    addr: int


class PixelBatchEvent(TypedDict):
    type: Literal["pixels"]
    pixels: list[list[int]]


class LogEvent(TypedDict):
    type: Literal["log"]
    line: str


class SignalEvent(TypedDict):
    type: Literal["heartbeat", "done"]


class ErrorEvent(TypedDict):
    type: Literal["error"]
    message: str


type StreamEvent = (
    StartEvent | PixelEvent | PixelBatchEvent | LogEvent | SignalEvent | SnapshotEvent | ErrorEvent
)
