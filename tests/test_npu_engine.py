from __future__ import annotations

import re
import shutil

import pytest
from conftest import assert_register, memory_map, run_simulation

from src.cpu.simulation.emulator import run_emulator_snapshot
from src.cpu.simulation.runner import _assemble_program, run_snapshot


def _u16(value: int) -> int:
    return value & 0xFFFF


def _configure(fields: dict[str, str | int]) -> list[str]:
    lines: list[str] = []
    for name, value in fields.items():
        field = name.upper()
        if isinstance(value, str):
            lines.append(f"MOV R0, ={value}")
            lines.append(f"NPUCFG {field}, R0")
        elif not 0 <= value <= 4095:
            lines.append(f"MOV R0, ={value & 0xFFFF}")
            lines.append(f"NPUCFG {field}, R0")
        else:
            lines.append(f"NPUCFG {field}, V{value}")
    return lines


def _stride(x: int, y: int) -> int:
    return (y << 8) | x


def _assert_loaded(output: str, value: int, register: int) -> None:
    pattern = (
        rf"MEM_LOAD: Loaded value {value} \(0x[0-9a-f]+\) "
        rf"from address \d+ into R{register}\b"
    )
    assert re.search(pattern, output) is not None, (
        f"R{register} was not loaded with {value}"
    )


def test_fully_connected_layer_applies_bias_then_requantization() -> None:
    output, _ = run_simulation([
        "space:",
        "    inp  = {{1, 2, 3, 4}}",
        "    wts  = {{1,1,1,1},{1,255,1,255}}",
        "    bias = {{10,0,0,0},{20,0,0,0}}",
        "    outp: 2",
        "main:",
        *_configure({
            "mode": 0, "flags": 0,
            "in_base": "inp", "in_w": 1, "in_h": 1, "in_c": 4,
            "w_base": "wts", "b_base": "bias",
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 2,
            "k_w": 1, "k_h": 1, "stride": _stride(1, 1), "pad": 0,
            "mult": 16384, "shift": 0,
        }),
        "NPURUN R1",
        "MOV R2, [outp]",
        "MOV R3, =outp",
        "ADD R3, R3, V1",
        "MOV R4, [R3]",
    ])

    assert "NPURUN: engine finished" in output
    _assert_loaded(output, 10, 2)
    _assert_loaded(output, 9, 4)


def test_convolution_pads_with_zeros_and_walks_the_output_plane() -> None:
    source = "\n".join([
        "space:",
        "    img  = {{1,2,3},{4,5,6},{7,8,9}}",
        "    wts  = {{1,1,1},{1,1,1},{1,1,1}}",
        "    bias: 4",
        "    outp: 9",
        "main:",
        *_configure({
            "mode": 0, "flags": 0,
            "in_base": "img", "in_w": 3, "in_h": 3, "in_c": 1,
            "w_base": "wts", "b_base": "bias",
            "out_base": "outp", "out_w": 3, "out_h": 3, "out_c": 1,
            "k_w": 3, "k_h": 3, "stride": _stride(1, 1), "pad": _stride(1, 1),
        }),
        "NPURUN R1",
    ])

    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")
    _, labels = _assemble_program(source.splitlines())
    snapshot = run_snapshot(source, mem_start=0, mem_end=64, max_cycles=40_000)

    memory = memory_map(snapshot)
    base = labels["outp"]
    assert [memory[base + i] for i in range(9)] == [12, 21, 16, 27, 45, 33, 24, 39, 28]


def test_depthwise_convolution_keeps_channels_separate() -> None:
    output, _ = run_simulation([
        "space:",
        "    img  = {{1,2},{3,4},{5,6},{7,8}}",
        "    wts  = {{1,1},{1,1},{1,1},{1,1}}",
        "    bias: 8",
        "    outp: 2",
        "main:",
        *_configure({
            "mode": 1, "flags": 0,
            "in_base": "img", "in_w": 2, "in_h": 2, "in_c": 2,
            "w_base": "wts", "b_base": "bias",
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 2,
            "k_w": 2, "k_h": 2, "stride": _stride(1, 1), "pad": 0,
        }),
        "NPURUN R1",
        "MOV R2, [outp]",
        "MOV R3, =outp",
        "ADD R3, R3, V1",
        "MOV R4, [R3]",
    ])

    _assert_loaded(output, 16, 2)
    _assert_loaded(output, 20, 4)


def test_max_pooling_reduces_a_window_to_its_largest_element() -> None:
    output, _ = run_simulation([
        "space:",
        "    img  = {{1,2},{3,4}}",
        "    outp: 1",
        "main:",
        *_configure({
            "mode": 2, "flags": 0,
            "in_base": "img", "in_w": 2, "in_h": 2, "in_c": 1,
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 1,
            "k_w": 2, "k_h": 2, "stride": _stride(2, 2), "pad": 0,
        }),
        "NPURUN R1",
        "MOV R2, [outp]",
    ])

    _assert_loaded(output, 4, 2)


def test_average_pooling_divides_through_the_output_scale() -> None:
    output, _ = run_simulation([
        "space:",
        "    img  = {{1,2},{3,4}}",
        "    outp: 1",
        "main:",
        *_configure({
            "mode": 3, "flags": 0,
            "in_base": "img", "in_w": 2, "in_h": 2, "in_c": 1,
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 1,
            "k_w": 2, "k_h": 2, "stride": _stride(2, 2), "pad": 0,
            "mult": 8192,
        }),
        "NPURUN R1",
        "MOV R2, [outp]",
    ])

    _assert_loaded(output, 3, 2)


def test_table_activation_maps_every_element_through_the_lut() -> None:
    output, _ = run_simulation([
        "space:",
        "    inp  = {{0, 1, 2, 3}}",
        "    lut  = {{9, 8, 7, 6}}",
        "    outp: 4",
        "main:",
        *_configure({
            "mode": 4, "flags": 0,
            "in_base": "inp", "lut_base": "lut",
            "out_base": "outp", "out_w": 4, "out_h": 1, "out_c": 1,
        }),
        "NPURUN R1",
        "MOV R2, [outp]",
        "MOV R3, =outp",
        "ADD R3, R3, V3",
        "MOV R4, [R3]",
    ])

    _assert_loaded(output, 9, 2)
    _assert_loaded(output, 6, 4)


def test_argmax_returns_the_index_of_the_largest_signed_value() -> None:
    output, _ = run_simulation([
        "space:",
        "    logits = {{3, 9, 2, 9}}",
        "    signed_logits = {{200, 250, 5}}",
        "    outp: 1",
        "main:",
        *_configure({
            "mode": 5, "flags": 0,
            "in_base": "logits",
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 4,
        }),
        "NPURUN R1",
        *_configure({"in_base": "signed_logits", "out_c": 3}),
        "NPURUN R2",
    ])

    assert_register(output, 1, 1)
    assert_register(output, 2, 2)


def test_input_zero_point_is_removed_before_the_multiply() -> None:
    output, _ = run_simulation([
        "space:",
        "    inp  = {{10, 10, 10, 10}}",
        "    wts  = {{1, 1, 1, 1}}",
        "    bias = {{7,0,0,0}}",
        "    outp: 1",
        "main:",
        *_configure({
            "mode": 0, "flags": 0,
            "in_base": "inp", "in_w": 1, "in_h": 1, "in_c": 4,
            "w_base": "wts", "b_base": "bias",
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 1,
            "k_w": 1, "k_h": 1, "stride": _stride(1, 1), "pad": 0,
            "in_zp": 10,
        }),
        "NPURUN R1",
        "MOV R2, [outp]",
    ])

    _assert_loaded(output, 7, 2)


def test_activation_clamp_fuses_relu6_into_the_output_pipeline() -> None:
    output, _ = run_simulation([
        "space:",
        "    inp  = {{1, 2, 3, 4}}",
        "    wts  = {{1,1,1,1},{255,255,255,255}}",
        "    bias: 8",
        "    outp: 2",
        "main:",
        *_configure({
            "mode": 0, "flags": 4,
            "in_base": "inp", "in_w": 1, "in_h": 1, "in_c": 4,
            "w_base": "wts",
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 2,
            "k_w": 1, "k_h": 1, "stride": _stride(1, 1), "pad": 0,
            "act_min": 0, "act_max": 6,
        }),
        "NPURUN R1",
        "MOV R2, [outp]",
        "MOV R3, =outp",
        "ADD R3, R3, V1",
        "MOV R4, [R3]",
    ])

    _assert_loaded(output, 6, 2)
    _assert_loaded(output, 0, 4)


def test_partial_accumulation_chains_a_reduction_wider_than_one_window() -> None:
    output, _ = run_simulation([
        "space:",
        "    inp  = {{1,2,3,4},{5,6,7,8}}",
        "    wts  = {{1, 1, 1, 1}}",
        "    accs: 4",
        "    outp: 1",
        "main:",
        *_configure({
            "mode": 0, "flags": 6,
            "in_base": "inp", "in_w": 1, "in_h": 1, "in_c": 4,
            "w_base": "wts", "acc_base": "accs",
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 1,
            "k_w": 1, "k_h": 1, "stride": _stride(1, 1), "pad": 0,
        }),
        "NPURUN R1",
        "MOV R0, =inp",
        "ADD R0, R0, V4",
        "NPUCFG IN_BASE, R0",
        "NPUCFG FLAGS, V1",
        "NPURUN R2",
        "MOV R3, [outp]",
    ])

    _assert_loaded(output, 36, 3)


def test_engine_reports_shape_and_capacity_errors_in_rd() -> None:
    output, _ = run_simulation([
        "space:",
        "    outp: 4",
        "main:",
        *_configure({
            "mode": 0, "flags": 4,
            "in_base": "outp", "in_w": 1, "in_h": 1, "in_c": 1,
            "w_base": "outp", "out_base": "outp",
            "out_w": 1, "out_h": 1, "out_c": 0,
            "k_w": 1, "k_h": 1,
        }),
        "NPURUN R1",
        "NPUCFG OUT_C, V1",
        "NPUCFG K_W, V32",
        "NPUCFG K_H, V32",
        "NPURUN R2",
        "NPUCFG K_W, V1",
        "NPUCFG K_H, V1",
        "NPURUN R3",
    ])

    assert_register(output, 1, 1)
    assert_register(output, 2, 2)
    assert "NPURUN: engine finished, result 4" in output


def test_engine_agrees_with_the_scalar_loop_it_replaces() -> None:
    output, _ = run_simulation([
        "space:",
        "    inp  = {{3, 1, 4, 1, 5, 9, 2, 6}}",
        "    wts  = {{1, 255, 1, 255, 1, 255, 1, 255}}",
        "    bias: 4",
        "    outp: 1",
        "main:",
        *_configure({
            "mode": 0, "flags": 4,
            "in_base": "inp", "in_w": 1, "in_h": 1, "in_c": 8,
            "w_base": "wts",
            "out_base": "outp", "out_w": 1, "out_h": 1, "out_c": 1,
            "k_w": 1, "k_h": 1, "stride": _stride(1, 1), "pad": 0,
        }),
        "NPURUN R1",
        "MOV R2, [outp]",
        "SXTB R2, R2",
        "MOV R3, V0",
        "MOV R4, =inp",
        "MOV R5, =wts",
        "MOV R6, V0",
        "loop:",
        "MOV R7, [R4]",
        "SXTB R7, R7",
        "MOV R8, [R5]",
        "SXTB R8, R8",
        "MADD R3, R7, R8",
        "ADD R4, R4, V1",
        "ADD R5, R5, V1",
        "ADD R6, R6, V1",
        "CMP R6, V8",
        "BNE loop",
    ])

    assert_register(output, 2, _u16(-3))
    assert_register(output, 3, _u16(-3))


@pytest.mark.parametrize(
    "mode_fields",
    [
        {"mode": 0, "k_w": 3, "k_h": 3, "pad": (1 << 8) | 1, "out_w": 3, "out_h": 3},
        {"mode": 2, "k_w": 2, "k_h": 2, "pad": 0, "out_w": 1, "out_h": 1},
        {"mode": 3, "k_w": 3, "k_h": 3, "pad": 0, "out_w": 1, "out_h": 1, "mult": 3641},
    ],
)
def test_fast_emulator_matches_rtl_for_the_tensor_engine(mode_fields: dict[str, str | int]) -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available on PATH")

    fields: dict[str, str | int] = {
        "flags": 0,
        "in_base": "img", "in_w": 3, "in_h": 3, "in_c": 1,
        "w_base": "wts", "b_base": "bias",
        "out_base": "outp", "out_c": 1,
        "stride": _stride(1, 1),
        "in_zp": 2,
    }
    fields.update(mode_fields)
    source = "\n".join([
        "space:",
        "    img  = {{1,250,3},{4,5,200},{7,8,9}}",
        "    wts  = {{1,255,1},{1,1,255},{1,1,1}}",
        "    bias = {{5,0,0,0}}",
        "    outp: 9",
        "main:",
        *_configure(fields),
        "NPURUN R1",
    ])

    image, labels = _assemble_program(source.splitlines())
    fast = run_emulator_snapshot(
        image, labels=labels, mem_start=0, mem_end=80, max_cycles=60_000
    )
    rtl = run_snapshot(source, mem_start=0, mem_end=80, max_cycles=60_000)

    assert fast["registers"] == rtl["registers"]
    assert fast["memory"] == rtl["memory"]
