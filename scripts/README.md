# Scripts

Grouped by what they talk to, so a directory answers "where does this belong"
without reading the file.

```
encode.ps1     the build step: src/cpu/encoder/file.de1 -> file.mif, data.mif,
               file.hex, program_size.svh
board/         talks to the physical DE1-SoC over JTAG
ml/            builds the models: trains, exports, downloads training text,
               and drives the exported demo through the simulator
models/        the model data those tools read and write -- see its own README
perf/          test-timing history and the chart drawn from it
```

`encode.ps1` sits at the top rather than in `board/` because it is the command
run most often, and because its output feeds both Quartus and the simulator, so
neither directory owns it.

`ml/` is code and `models/` is data. Keeping them apart is why a model's corpus
never has to be told from another model's by a filename prefix.

## Commands

```powershell
.\scripts\encode.ps1                                     # encode the active program
uv run python scripts/ml/evaluate.py                     # score the committed checkpoint
uv run python scripts/ml/fetch_corpus.py                 # re-download the public-domain corpus
uv run python scripts/perf/track_test_performance.py --no-record
```

`scripts/ml/tinyml_export.py` compiles a quantized model description into a
`.de1` program; [quantized inference](../docs/tinyml.md) documents its contract,
and `scripts/models/README.md` gives the exact command per model.

Everything here is a standalone entry point, run from the repository root. The
assembler itself is a package and is run as `python -m src.cpu.encoder.main`,
never by path.
