# Assembly encoder

The encoder converts a `.de1` assembly source into the flat binary image loaded
by the CPU. Read only the reference needed for the task:

| Topic | Canonical reference |
|-------|---------------------|
| Source shape, operands, data, labels and strings | [Assembly syntax](../../../docs/assembly.md) |
| Instruction encoding and behavior | [ISA](../../../docs/isa.md) |
| VGA pixel/text operations | [VGA and text](../../../docs/vga.md) |
| Quantized inference, vector registers, tensor engine | [TinyML](../../../docs/tinyml.md) |
| Matrix literals and multiplication | [Matrices](../../../docs/matrices.md) |
| Memory layout, loading and execution timing | [Architecture](../../../docs/architecture.md) |
| Encoder stages, utilities and simulation | [Toolchain](../../../docs/toolchain.md) |

The complete routing index is [HOW_CPU_WORKS.md](../../../HOW_CPU_WORKS.md).

## Commands

Encode one source file:

```powershell
python -m src.cpu.encoder.main path/to/program.de1
```

The binary is written to `src/cpu/encoder/out/<name>.bin`. For the active
board program and all MIF/HEX conversions, run from the repository root:

```powershell
.\scripts\encode.ps1
```

## Source shape

```text
space:
    counter = 00000000
    pi      = F3.5
    message = "Hi"
    buffer: 256

main:
    MOV R0, [counter]
    ADD R0, V1
    SAVE R0, [counter]
```

The optional `space:` section declares data; code supports labels and `#`
comments. [Assembly syntax](../../../docs/assembly.md) is the complete
reference for declaration forms, operand forms, shorthand and condition
suffixes do not duplicate it here.

## Pipeline

`assemble.py` drives the stages under `steps/` to lay out data, normalize
shorthand, resolve labels and emit instructions; `main.py` is only the CLI
around it, and `src/cpu/simulation/runner.py` assembles through the same
module, so the board image and the simulated one cannot diverge.

`steps/memory.py` owns the data section end to end the `space:` declarations
plus the TEXT, matrix and float blobs the code implies and hands back one
`DataSection`. `analyze.py` calls it too, with an `on_error` sink that turns a
rejected declaration into an editor diagnostic instead of an exception, so the
editor and the build agree on every address by construction.

`steps/npu.py` owns the vector and tensor instruction class, whose operand
shapes the generic path cannot express; it also supplies the `NPU_*` constants
every program has in scope, and the emulator and model exporter read their
modes and flags from those same tables. Utilities under `utils/` convert the
binary to:

- byte-oriented text hex (`utils/bin2hex.py`);
- 8- or 32-bit Quartus MIF (`utils/hex_to_mif.py`).

The root encoding script also updates tracked `program_size.svh`, which gives
the real loader the exact length of canonical `file.hex`.

Generated intermediates belong in `out/` and are ignored by Git.
