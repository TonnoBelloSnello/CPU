# CPU

## Setup and tests

Install [uv](https://docs.astral.sh/uv/) and Icarus Verilog (`iverilog` and
`vvp`), then run:

```powershell
uv sync
uv run pytest
```

Useful focused commands:

```powershell
uv run pytest tests/test_vga.py
uv run pytest tests/test_npu_engine.py tests/test_vector_ops.py tests/test_quant_ops.py
uv run python .\scripts\track_test_performance.py --no-record
uv run ruff check .      # lint
uv run ty check          # types
```

Both `ruff` and `ty` are expected to report no findings; their configuration
lives in `pyproject.toml`.

## Encode the active board program

Edit `src/cpu/encoder/file.de1`, then run:

```powershell
.\scripts\encode.ps1
```

This refreshes the tracked `file.mif`, `data.mif`, `file.hex` and
`program_size.svh`.
Intermediate output is written under `src/cpu/encoder/out/`.

Includes are relative to the file containing them. When copying a reusable
program into `src/cpu/encoder/file.de1`, adjust its include paths to that
directory. The VGA digits demo uses `include "data/digits8x8_weights.de1"`
under `programs/`; the active board copy uses
`include "../../../programs/data/digits8x8_weights.de1"`. The included file
opens `space:` and declares the weights, so the caller continues with its
buffers without another `space:`. Save all included files before encoding.

Reusable demos are under `programs/`, including three TinyML ones:
`tinyml_digits.de1` (one inference, result on HEX/LEDR), `tinyml_bench.de1`
(the same layer three ways, timed) and `tinyml_vga_digits.de1` (ten
pseudo-randomly corrupted digits classified and drawn side by side on the
VGA framebuffer, green for a correct call and red for a wrong one).
The Quartus project is
`quartus/CPUFrFr.qpf`; its QSF references the canonical sources in `hdl/`
and the root MIF files directly.

## Run a model

`scripts/ml/tinyml_export.py` compiles a JSON description of an already-quantized
INT8 model into a complete `.de1` program tensors in the data section, one
`NPUCFG`/`NPURUN` block per layer:

```powershell
uv run python scripts/ml/tinyml_export.py scripts/models/digits8x8/model.json -o programs/tinyml_digits.de1
```

The JSON must already use the engine's supported shapes and quantization
parameters; converting TFLite scales and per-channel weights is a separate
step. See the [quantization contract](docs/tinyml.md#quantization-model).
`programs/tinyml_digits.de1` is the committed output of that command, and a
test regenerates it so the program cannot drift from its model.

## Web simulator

```powershell
uv run uvicorn src.cpu.web.app:app --reload
```

Open <http://127.0.0.1:8000>.

The editor defaults to **FAST**, an architectural simulator intended for quick
edit/run feedback.  Select **RTL (cycle-accurate)** beside the Run button
when debugging pipeline or timing-sensitive behaviour; its compiled Icarus
harness is cached between runs.  The register panel shows the vector registers
`Q0`–`Q7` and accumulators `A0`–`A3` alongside the general ones.

Cycle counts differ by engine on purpose: the RTL counts clock edges, while
the architectural simulator counts instruction steps and virtual waits.
Only the RTL count measures hardware execution time.

The UI is styled with Tailwind, compiled ahead of time into
`src/cpu/web/static/styles.css`, which is committed: serving the simulator needs
Python only for the FAST engine; RTL execution also needs Icarus Verilog.
After editing `src/cpu/web/styles/app.css` or any class name under
`src/cpu/web/static/`, rebuild it:

```powershell
cd src/cpu/web
npm install
npm run build:css   # npm run watch:css rebuilds on save
```
