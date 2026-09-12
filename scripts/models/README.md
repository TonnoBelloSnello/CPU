# Models

One directory per model. Each holds everything that model needs and nothing
another one uses, so a demo's data never has to be told apart from its
neighbour's by filename prefix.

```
digits8x8/
  model.json                  quantized INT8 stencils, the input to tinyml_export.py
```

## digits8x8

An already-quantized handwritten-digit classifier. `model.json` is the input to
the exporter, and the committed program is regenerated from it rather than
edited:

```powershell
uv run python scripts/ml/tinyml_export.py scripts/models/digits8x8/model.json -o programs/tinyml_digits.de1
```

See [quantized inference](../../docs/tinyml.md).
