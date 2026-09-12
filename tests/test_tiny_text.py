from __future__ import annotations

import copy
import shutil

import pytest
import torch

from scripts.ml.evaluate import report
from scripts.ml.simulate import await_input, press_key, select_key, type_prompt
from scripts.ml.tiny_text import (
    CONTEXT,
    LINE_CHARS,
    MAX_PROMPT,
    PROGRAM,
    PROMPTS,
    WEIGHTS,
    compile_program,
    compile_weights,
    generate,
    load_model,
    reference_step,
)
from src.cpu.encoder.assemble import AssembledProgram, assemble
from src.cpu.simulation.emulator import CPUEmulator
from src.cpu.simulation.parser import SnapshotParser
from src.cpu.simulation.rtl_config import LOADER_MAX_PROGRAM_SIZE, RAM_ADDR_WIDTH
from src.cpu.simulation.runner import _compiled_icarus_workspace, _run_command
from src.cpu.simulation.templates import render_loader_sv, render_runtime_testbench


def boot(prompt: str = "") -> tuple[AssembledProgram, CPUEmulator]:
    program = assemble(compile_program(load_model(), prompt).splitlines())
    cpu = CPUEmulator(program.to_bytes())
    await_input(cpu)
    assert cpu.memory[program.symbols["ready"]] == 1
    return program, cpu


def read_text(program: AssembledProgram, cpu: CPUEmulator, name: str) -> str:
    base = program.symbols[name]
    return bytes(cpu.memory[base : base + LINE_CHARS + 1]).split(b"\0")[0].decode("ascii")


def test_separate_weights_and_inline_export_have_identical_images() -> None:
    model = load_model()
    source = compile_program(model, inline=False)
    assert source == PROGRAM.read_text(encoding="utf-8")
    assert compile_weights(model) == WEIGHTS.read_text(encoding="utf-8")
    assert "hidden_w =" not in source
    included = assemble(source.splitlines(), PROGRAM.parent)
    inline = assemble(compile_program(model).splitlines())
    assert included.to_bytes() == inline.to_bytes()
    assert included.symbols == inline.symbols
    assert len(included.to_bytes()) <= LOADER_MAX_PROGRAM_SIZE


def test_improved_checkpoint_on_training_and_unseen_sentences() -> None:
    model = load_model()
    scores = report(model)
    for label, accuracy, terminated, invented, repeated in (
        ("domain", 61.5, 98.0, 3.0, 6.0),
        ("book", 30.0, 94.0, 28.0, 3.0),
    ):
        assert scores[label]["accuracy"] >= accuracy, (label, scores[label])
        assert scores[label]["terminated"] >= terminated, (label, scores[label])
        assert scores[label]["invented"] <= invented, (label, scores[label])
        assert scores[label]["repeated"] <= repeated, (label, scores[label])

    assert generate(model, "LA CPU") == "LA CPU LEGGE I DATI."
    assert generate(model, "IL GATTO") == "IL GATTO SALTA SUL MURETTO."
    assert generate(model, "IL SOLE") == "IL SOLE SCENDE DIETRO GLI ALBERI."


@pytest.mark.parametrize("prompt", [*PROMPTS, "IL ROBOT", "IL GATTO", "LA MEMORIA", "A"])
def test_interactive_inference_matches_integer_reference(prompt: str) -> None:
    model = load_model()
    program, cpu = boot(prompt)
    select_key(cpu, program.symbols, 31)
    press_key(cpu, program.symbols, 4)
    expected = generate(model, prompt)
    assert read_text(program, cpu, "generated") == expected
    assert cpu.hex == len(expected)
    assert cpu.led == 1
    assert cpu.memory[program.symbols["generation_count"]] == 1
    context = [model.alphabet.index(c) for c in expected.rjust(CONTEXT)[-CONTEXT:]]
    base = program.symbols["context"]
    assert list(cpu.memory[base : base + CONTEXT]) == context
    previous = expected[:-1].rjust(CONTEXT)[-CONTEXT:]
    hidden, logits, _ = reference_step(model, [model.alphabet.index(c) for c in previous])
    for name, values in (("hidden", hidden), ("logits", logits)):
        base = program.symbols[name]
        assert list(cpu.memory[base : base + len(values)]) == [v & 255 for v in values]


def test_navigation_wraps_and_every_letter_is_typeable() -> None:
    program, cpu = boot()
    labels = program.symbols
    press_key(cpu, labels, 1)
    assert cpu.memory[labels["selected"]] == 7
    press_key(cpu, labels, 8)
    assert cpu.memory[labels["selected"]] == 0
    for expected in (8, 16, 24, 0):
        press_key(cpu, labels, 2)
        assert cpu.memory[labels["selected"]] == expected
    for text in ("ABCDEFGHIJKLMNOPQRSTUVWX", "YZ., "):
        select_key(cpu, labels, 30)
        press_key(cpu, labels, 4)
        type_prompt(cpu, labels, text)
        assert read_text(program, cpu, "prompt") == text


def test_editing_limits_empty_generate_and_shorter_second_output() -> None:
    program, cpu = boot()
    labels = program.symbols
    select_key(cpu, labels, 31)
    press_key(cpu, labels, 4)
    assert cpu.memory[labels["generation_count"]] == 0
    type_prompt(cpu, labels, "A" * MAX_PROMPT)
    select_key(cpu, labels, 1)
    press_key(cpu, labels, 4)
    assert read_text(program, cpu, "prompt") == "A" * MAX_PROMPT
    select_key(cpu, labels, 29)
    press_key(cpu, labels, 4)
    assert read_text(program, cpu, "prompt") == "A" * (MAX_PROMPT - 1)
    select_key(cpu, labels, 30)
    press_key(cpu, labels, 4)
    select_key(cpu, labels, 29)
    press_key(cpu, labels, 4)
    assert read_text(program, cpu, "prompt") == ""
    row_chars = LINE_CHARS // 3
    wrapping, single_row = "LA RETE", "IL MODELLO"
    for text in (wrapping, single_row):
        select_key(cpu, labels, 30)
        press_key(cpu, labels, 4)
        type_prompt(cpu, labels, text)
        select_key(cpu, labels, 31)
        press_key(cpu, labels, 4)
        assert read_text(program, cpu, "generated") == generate(load_model(), text)
    assert cpu.memory[labels["generation_count"]] == 2
    assert len(generate(load_model(), wrapping)) > row_chars
    assert len(read_text(program, cpu, "generated")) <= row_chars
    assert not any(cpu.framebuffer[y * 160 + x] for y in range(39, 57) for x in range(8, 152))


def test_held_buttons_chords_and_unstable_presses_do_not_duplicate_input() -> None:
    program, cpu = boot()
    labels = program.symbols
    cpu.key_mask = 4
    for _ in range(100_000):
        cpu.step()
    assert read_text(program, cpu, "prompt") == "A"
    cpu.key_mask = 0
    await_input(cpu)
    press_key(cpu, labels, 3)
    assert read_text(program, cpu, "prompt") == "A"
    assert cpu.memory[labels["selected"]] == 0
    cpu.key_mask = 4
    cpu.step()
    cpu.key_mask = 0
    await_input(cpu)
    assert read_text(program, cpu, "prompt") == "A"
    press_key(cpu, labels, 4)
    assert read_text(program, cpu, "prompt") == "AA"


def test_weight_sensitivity_and_maximum_generation_budget() -> None:
    model = copy.deepcopy(load_model())
    model.output_w = torch.zeros_like(model.output_w)
    model.output_b = torch.zeros_like(model.output_b)
    model.output_b[model.alphabet.index("A")] = 1 << (model.logit_shift + 4)
    program = assemble(compile_program(model, "CIAO").splitlines())
    cpu = CPUEmulator(program.to_bytes())
    await_input(cpu)
    select_key(cpu, program.symbols, 31)
    press_key(cpu, program.symbols, 4)
    assert read_text(program, cpu, "generated") == "CIAO" + "A" * (LINE_CHARS - 4)
    assert cpu.memory[program.symbols["output_len"]] == LINE_CHARS
    assert not cpu.halted


def key_sequence(text: str) -> list[int]:
    sequence: list[int] = []
    selected = 0
    for target in ["ABCDEFGHIJKLMNOPQRSTUVWXYZ., ".index(c) for c in text] + [31]:
        while selected // 8 != target // 8:
            sequence.append(2)
            selected = (selected + 8) % 32
        while selected != target:
            sequence.append(8)
            selected = (selected & 24) | ((selected + 1) & 7)
        sequence.append(4)
    return sequence


def test_physical_key_pins_and_vga_match_fast_under_rtl() -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available")
    program, cpu = boot()
    keys = key_sequence("LA CPU")
    for mask in keys:
        press_key(cpu, program.symbols, mask)
    tb = render_runtime_testbench("TextKeyboardTB", RAM_ADDR_WIDTH, 8)
    tb = tb.replace("reg clock = 1'b0;", "reg clock = 1'b0; reg finished = 0;")
    tb = tb.replace(
        "integer addr;",
        f"integer addr; wire [7:0] ui_ready = dut.storage.ram[{program.symbols['ready']}];",
    )
    tb = tb.replace("while (!dut.halted", "while (!finished").replace(
        "if (!dut.halted)", "if (!finished)"
    )
    actions = [
        f"""
        wait (dut.executer.state == cpu_pkg::EX_WAIT_KEY);
        @(negedge clock); KEY = 4'd{15 ^ mask};
        wait (ui_ready == 0);
        wait (ui_ready == 1);
        repeat (100) @(negedge clock);
        KEY = 4'd15;
        wait (dut.executer.state == cpu_pkg::EX_WAIT_KEY);
        """
        for mask in keys
    ]
    stimulus = "initial begin\n" + "\n".join(actions) + "\nfinished = 1;\nend\n"
    tb = tb.replace("endmodule", stimulus + "endmodule")
    with _compiled_icarus_workspace(
        program.to_bytes(),
        executable_name="text_keyboard",
        top_module="TextKeyboardTB",
        defines=("SIMULATION", "WEB_FAST_SIMULATION", "SNAPSHOT_MODE"),
        testbench_name="text_keyboard_tb.sv",
        testbench_text=tb,
        loader_text=render_loader_sv(program.to_bytes(), addr_width=RAM_ADDR_WIDTH),
    ) as (path, executable):
        result = _run_command(
            [
                "vvp",
                str(executable),
                "+MEM_START=0",
                "+MEM_END=450",
                "+MAX_CYCLES=8000000",
                "+KEY_MASK=0",
            ],
            path,
        )
    assert "Simulation timeout" not in result.stdout
    parser = SnapshotParser(RAM_ADDR_WIDTH, 8)
    for line in result.stdout.splitlines():
        parser.feed_line(line)
    for cell in parser.memory:
        assert cell["dec"] == cpu.memory[cell["addr"]]
    pixels = {c["addr"]: c["dec"] for c in parser.framebuffer if c["dec"]}
    assert pixels == {i: value for i, value in enumerate(cpu.framebuffer) if value}
    assert parser.registers["LE"]["dec"] == 1
    assert read_text(program, cpu, "generated") == generate(load_model(), "LA CPU")


def test_export_rejects_invalid_prompt_and_shape() -> None:
    model = load_model()
    for prompt in ("X" * 25, "ciao", "?"):
        with pytest.raises(ValueError, match="24 supported characters"):
            compile_program(model, prompt)
    model.hidden_w = model.hidden_w[:0]
    with pytest.raises(ValueError, match="height"):
        compile_program(model)
