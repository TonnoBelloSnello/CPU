"""Compile a quantized model description into a ``.de1`` program.

It lays the model's tensors out in the data section and emits the
``NPUCFG``/``NPURUN`` sequence that runs each layer on the tensor engine. The
JSON is a flat view already adapted to the engine: reading a TFLite model,
requantizing per-channel weights to per-tensor and deriving the multiplier and
shift is a separate converter's job. docs/tinyml.md has the full contract.

===========================  ====================================================
JSON field                   Source or required adaptation
===========================  ====================================================
``weights``                  the filter tensor's ``int8`` buffer, in its native
                             layout (``[out_c][k_h][k_w][in_c]`` for a
                             convolution, ``[out_c][in_c]`` for a dense layer,
                             ``[k_h][k_w][channels]`` for depthwise with
                             depth multiplier 1)
``bias``                     the bias tensor's ``int32`` buffer
``output_multiplier``        unsigned 16-bit MULT, with 15 fractional bits;
                             derive it with SHIFT so that MULT / 2**15 /
                             2**SHIFT approximates the required scale.
                             MULT=0 skips multiplication, not a zero scale.
``output_shift``             SHIFT, a right shift in 0..31
``input_zero_point``         the input tensor's ``quantization.zero_point``
``output_zero_point``        the output tensor's ``quantization.zero_point``
                             for convolution/depthwise; pooling operates on
                             raw bytes, so this field is an additive offset
``activation``               ``[quantized_activation_min,
                             quantized_activation_max]``
===========================  ====================================================

Pooling needs an explicit multiplier for averaging and does not adjust it for the
valid elements in padded border windows.

    python scripts/ml/tinyml_export.py scripts/models/digits8x8/model.json -o programs/out.de1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cpu.encoder.steps.npu import (  # noqa: E402
    NPU_BUILTIN_CONSTANTS,
    NPU_PATCH_DEPTH,
)

MODE_BY_LAYER: dict[str, int] = {
    "conv2d": NPU_BUILTIN_CONSTANTS["NPU_CONV"],
    "fully_connected": NPU_BUILTIN_CONSTANTS["NPU_CONV"],
    "depthwise_conv2d": NPU_BUILTIN_CONSTANTS["NPU_DEPTHWISE"],
    "max_pool_2d": NPU_BUILTIN_CONSTANTS["NPU_MAXPOOL"],
    "average_pool_2d": NPU_BUILTIN_CONSTANTS["NPU_AVGPOOL"],
    "lut": NPU_BUILTIN_CONSTANTS["NPU_LUT"],
    "argmax": NPU_BUILTIN_CONSTANTS["NPU_ARGMAX"],
}
NPU_NO_BIAS: int = NPU_BUILTIN_CONSTANTS["NPU_NO_BIAS"]
WEIGHTED_LAYERS = frozenset({"conv2d", "fully_connected", "depthwise_conv2d"})
POOL_LAYERS = frozenset({"max_pool_2d", "average_pool_2d"})

Shape = tuple[int, int, int]
Fields = dict[str, "str | int"]  # an integer immediate, or a label


class ExportError(ValueError):
    pass


def as_bytes(values: list[int], what: str) -> list[int]:
    for value in values:
        if not -128 <= value <= 255:
            raise ExportError(f"{what} value {value} is outside the INT8/UINT8 range")
    return [value & 0xFF for value in values]


def int32_bytes(values: list[int], what: str) -> list[int]:
    for value in values:
        if not -(2**31) <= value < 2**31:
            raise ExportError(f"{what} value {value} does not fit an INT32")
    return [(value >> shift) & 0xFF for value in values for shift in (0, 8, 16, 24)]


def matrix(values: list[int], row: int | None = None) -> str:
    if not values:
        raise ExportError("cannot emit an empty tensor")
    if row is None or row <= 0 or len(values) % row:
        row = next(
            (w for w in range(min(32, len(values)), 0, -1) if len(values) % w == 0), len(values)
        )
    chunks = (values[i : i + row] for i in range(0, len(values), row))
    return "{" + ",".join("{" + ",".join(map(str, chunk)) + "}" for chunk in chunks) + "}"


def config(fields: Fields) -> list[str]:
    lines: list[str] = []
    for name, value in fields.items():
        if isinstance(value, int) and 0 <= value <= 4095:
            lines.append(f"    NPUCFG {name.upper()}, V{value}")
        else:
            immediate = value if isinstance(value, str) else value & 0xFFFF
            lines += [f"    MOV R0, ={immediate}", f"    NPUCFG {name.upper()}, R0"]
    return lines


def output_shape(layer: dict[str, Any], shape: Shape) -> Shape:
    kind = layer["type"]
    if kind == "fully_connected":
        return (1, 1, len(layer["bias"]))
    if kind == "argmax":
        return (1, 1, 1)
    if kind == "lut":
        return shape
    kernel_h, kernel_w = layer["kernel"]
    stride_x, stride_y = layer.get("stride", [1, 1])
    pad_x, pad_y = layer.get("pad", [0, 0])
    out_h = (shape[0] + 2 * pad_y - kernel_h) // stride_y + 1
    out_w = (shape[1] + 2 * pad_x - kernel_w) // stride_x + 1
    if out_h <= 0 or out_w <= 0:
        raise ExportError(f"layer '{layer.get('name', kind)}' has an empty output plane")
    return (out_h, out_w, len(layer["bias"]) if kind == "conv2d" else shape[2])


def window_length(layer: dict[str, Any], shape: Shape) -> int:
    kind = layer["type"]
    if kind == "fully_connected":
        return shape[0] * shape[1] * shape[2]
    if kind in {"lut", "argmax"}:
        return 0
    kernel_h, kernel_w = layer["kernel"]
    return kernel_h * kernel_w * (shape[2] if kind == "conv2d" else 1)


def geometry_fields(layer: dict[str, Any], shape: Shape, in_zero_point: int) -> tuple[Fields, int]:
    fields: Fields = {}
    if layer["type"] == "fully_connected":
        kernel_h = kernel_w = 1
        fields |= {"in_w": 1, "in_h": 1, "in_c": shape[0] * shape[1] * shape[2]}
    else:
        kernel_h, kernel_w = layer["kernel"]
    stride_x, stride_y = layer.get("stride", [1, 1])
    pad_x, pad_y = layer.get("pad", [0, 0])
    act_min, act_max = layer.get("activation", [0, 0])
    fields |= {
        "k_w": kernel_w,
        "k_h": kernel_h,
        "stride": (stride_y << 8) | stride_x,
        "pad": (pad_y << 8) | pad_x,
        "in_zp": in_zero_point & 0xFF,
        "out_zp": int(layer.get("output_zero_point", 0)) & 0xFFFF,
        "mult": int(layer.get("output_multiplier", 0)),
        "shift": int(layer.get("output_shift", 0)),
        "act_min": int(act_min) & 0xFF,
        "act_max": int(act_max) & 0xFF,
    }
    return fields, kernel_w


def tensor_fields(
    layer: dict[str, Any], name: str, kernel_w: int, shape: Shape, out_c: int
) -> tuple[Fields, list[str]]:
    weights = as_bytes(list(layer["weights"]), f"{name} weights")
    row = kernel_w * shape[2] if layer["type"] == "depthwise_conv2d" else len(weights) // out_c
    data = [f"    {name}_w = {matrix(weights, row)}"]
    bias = layer.get("bias")
    if not bias:
        return {"flags": NPU_NO_BIAS, "w_base": f"{name}_w"}, data
    bias_bytes = int32_bytes(list(bias), f"{name} bias")
    data.append(f"    {name}_b = {matrix(bias_bytes, 4)}")
    return {"w_base": f"{name}_w", "b_base": f"{name}_b"}, data


def lut_fields(layer: dict[str, Any], name: str) -> tuple[Fields, list[str]]:
    table = as_bytes(list(layer["table"]), f"{name} table")
    if len(table) != 256:
        raise ExportError(f"layer '{name}' needs a 256-entry table")
    return {"lut_base": f"{name}_lut"}, [f"    {name}_lut = {matrix(table, 16)}"]


def compile_model(model: dict[str, Any]) -> str:
    spec = model["input"]
    shape: Shape = tuple(spec["shape"])
    if len(shape) != 3:
        raise ExportError("input shape must be [height, width, channels]")
    size = shape[0] * shape[1] * shape[2]

    buffer = spec.get("name", "input_buffer")
    if (values := spec.get("values")) is None:
        data_lines = [f"    {buffer}: {size}"]
    else:
        flat = as_bytes(list(values), "input")
        if len(flat) != size:
            raise ExportError("input values do not match the declared input shape")
        data_lines = [f"    {buffer} = {matrix(flat, shape[1] * shape[2])}"]
    code_lines: list[str] = []
    zero_point = int(spec.get("zero_point", 0))

    for index, layer in enumerate(model["layers"]):
        kind = layer["type"]
        if kind not in MODE_BY_LAYER:
            raise ExportError(f"unsupported layer type '{kind}'")
        name = layer.get("name", f"{kind}_{index}")
        out = output_shape(layer, shape)
        window = window_length(layer, shape)
        if window > NPU_PATCH_DEPTH:
            raise ExportError(
                f"layer '{name}' reduces over {window} elements, more than the engine's "
                f"{NPU_PATCH_DEPTH}-element window; split it and chain the passes with "
                "NPU_ACC_OUT / NPU_ACC_IN"
            )

        if kind == "argmax":
            code_lines.append(f"    # {name}: argmax over {shape[2]} logits")
            code_lines += config({
                "mode": MODE_BY_LAYER[kind],
                "flags": 0,
                "in_base": buffer,
                "out_base": buffer,
                "out_w": 1,
                "out_h": 1,
                "out_c": shape[0] * shape[1] * shape[2],
            })
            code_lines.append("    NPURUN R1")
            shape = out
            continue

        out_name = f"{name}_out"
        fields: Fields = {
            "mode": MODE_BY_LAYER[kind],
            "flags": 0,
            "in_base": buffer,
            "in_w": shape[1],
            "in_h": shape[0],
            "in_c": shape[2],
            "out_base": out_name,
            "out_w": out[1],
            "out_h": out[0],
            "out_c": out[2],
        }
        if kind == "lut":
            for field in ("in_w", "in_h", "in_c"):
                del fields[field]
            extra, data = lut_fields(layer, name)
        else:
            geometry, kernel_w = geometry_fields(layer, shape, zero_point)
            fields.update(geometry)
            if kind in WEIGHTED_LAYERS:
                extra, data = tensor_fields(layer, name, kernel_w, shape, out[2])
            else:
                extra, data = ({"flags": NPU_NO_BIAS} if kind in POOL_LAYERS else {}), []
        fields.update(extra)
        data_lines += data
        data_lines.append(f"    {out_name}: {out[0] * out[1] * out[2]}")
        code_lines.append(f"    # {name}: {kind} {shape} -> {out}")
        code_lines += config(fields)
        code_lines.append("    NPURUN R1")

        buffer, shape = out_name, out
        zero_point = int(layer.get("output_zero_point", 0))

    header = f"# {model.get('name', 'model')}: generated by scripts/ml/tinyml_export.py."
    return "\n".join([
        header + "  Do not edit by hand.",
        "# Runs one INT8 inference on the tensor engine and reports the result on",
        "# the HEX displays and LEDR.",
        "",
        "space:",
        *data_lines,
        "",
        "main:",
        "    BL infer",
        "    MOV HEX, R1",
        "    MOV LE, R1",
        "    B done",
        "",
        "infer:",
        *code_lines,
        "    MOV PC, LR",
        "",
        "done:",
    ]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("model", type=Path, help="JSON model description")
    parser.add_argument("-o", "--output", type=Path, help="destination .de1 file")
    args = parser.parse_args()

    try:
        source = compile_model(json.loads(args.model.read_text(encoding="utf-8")))
    except ExportError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.output is None:
        sys.stdout.write(source)
    else:
        args.output.write_text(source, encoding="utf-8")
        print(f"[INFO] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
