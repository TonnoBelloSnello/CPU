"""Train a small character MLP in PyTorch and export it to the CPU's NPU.

The model embeds each of the last CONTEXT characters into EMBED dimensions,
concatenates them and runs one ReLU hidden layer. What the embedding buys is
width, not context: a one-hot input spends VOCAB weights per hidden neuron per
position, and spending EMBED instead pays for a hidden layer twice as wide inside
the same image. Longer context was tried and is worse -- see docs/tiny-text.md.
This is a toy neural language model, with no attention or conversational ability.

It trains on two corpora at once: hand-written text about this CPU, which is what
the demo has to say, oversampled against public-domain Italian prose, which is
what teaches it to spell. It trains on corrupted contexts, because it generates
from its own output and never sees a clean one -- see CONTEXT_NOISE.

TextModel is the quantized checkpoint as a torch Module, exact in int64, so
calibration, the reference the tests hold the CPU to and what training quantizes
into are one implementation instead of three. scripts/ml/simulate.py drives the
exported program through the emulator.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import torch
from torch import Tensor, nn
from torch.nn.functional import cross_entropy, relu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cpu.encoder.assemble import assemble  # noqa: E402
from src.cpu.simulation.rtl_config import HDL_DIR, LOADER_MAX_PROGRAM_SIZE  # noqa: E402

LOG = logging.getLogger(__name__)
MODEL_DIR = ROOT / "scripts" / "models" / "tiny_text"
CHECKPOINT = MODEL_DIR / "checkpoint.json"
RUNTIME = MODEL_DIR / "runtime.de1"
CORPUS_DIR = MODEL_DIR / "corpus"
PROGRAM = ROOT / "programs" / "tinyml_text.de1"
WEIGHTS = ROOT / "programs" / "data" / "tiny_text_weights.de1"

CONTEXT = 12  # characters of context per prediction
EMBED = 16
HIDDEN = 256  # hidden units; caps the image size
EPOCHS = 20
BATCH = 1024
LEARNING_RATE = 3e-3
SEED = 42
CALIBRATION = 4096  # contexts the quantization shifts measure
CONTEXT_NOISE = 0.12  # fraction of a training context corrupted
DOMAIN_REPEATS = 60  # domain repeats in the corpus mix
SIMPLE_MAX_CHARS = 70
SIMPLE_VOCABULARY = 4800
LINE_CHARS = 72
MAX_PROMPT = 24
ALPHABET = " ,.ABCDEFGHIJKLMNOPQRSTUVWXYZ"
KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ., "
PROMPTS = ("LA CPU", "IL MODELLO", "LA RETE", "CIAO")

TENSORS = ("embed_w", "hidden_w", "hidden_b", "output_w", "output_b")
SCALARS = ("context_size", "embed_scale", "hidden_w_scale", "hidden_shift", "hidden_mult",
           "output_scale", "logit_shift", "logit_mult")
Values = Tensor | list[int] | list[list[int]]


def rounding_shift(value: Tensor, shift: int) -> Tensor:
    if shift == 0:
        return value
    return torch.where(value < 0, -1, 1) * ((value.abs() + (1 << (shift - 1))) >> shift)


def fixed_multiply(value: Tensor, mult: int) -> Tensor:
    if mult == 0:
        return value
    return (value * mult + 16384) >> 15


def as_int64(values: Values, name: str) -> Tensor:
    tensor = values if isinstance(values, Tensor) else torch.tensor(values)
    if tensor.dtype != torch.int64:
        raise ValueError(f"{name} must be whole numbers")
    return tensor


class CharMLP(nn.Module):
    def __init__(self, vocab: int, context: int, embed: int, hidden: int) -> None:
        super().__init__()
        self.embed = nn.Embedding(vocab, embed)
        self.hidden = nn.Linear(context * embed, hidden)
        self.output = nn.Linear(hidden, vocab)

    def forward(self, contexts: Tensor) -> Tensor:
        return self.output(relu(self.hidden(self.embed(contexts).flatten(1))))


class TextModel(nn.Module):
    embed_w: Tensor
    hidden_w: Tensor
    hidden_b: Tensor
    output_w: Tensor
    output_b: Tensor

    def __init__(
        self,
        alphabet: str,
        embed_w: Values,
        hidden_w: Values,
        hidden_b: Values,
        output_w: Values,
        output_b: Values,
        context_size: int = CONTEXT,
        embed_scale: int = 1,
        hidden_w_scale: int = 1,
        hidden_shift: int = 0,
        hidden_mult: int = 0,
        output_scale: int = 1,
        logit_shift: int = 0,
        logit_mult: int = 0,
    ) -> None:
        super().__init__()
        self.alphabet = alphabet
        self.context_size = context_size
        self.embed_scale = embed_scale
        self.hidden_w_scale = hidden_w_scale
        self.hidden_shift = hidden_shift
        self.hidden_mult = hidden_mult
        self.output_scale = output_scale
        self.logit_shift = logit_shift
        self.logit_mult = logit_mult
        weights = (embed_w, hidden_w, hidden_b, output_w, output_b)
        for name, values in zip(TENSORS, weights, strict=True):
            self.register_buffer(name, as_int64(values, name))
        self.validate()

    @property
    def embed_size(self) -> int:
        return self.embed_w.shape[1]

    def forward(self, contexts: Tensor) -> tuple[Tensor, Tensor]:
        embedded = self.embed_w[contexts].flatten(-2)
        accumulated = fixed_multiply(embedded @ self.hidden_w.T + self.hidden_b,
                                     self.hidden_mult)
        hidden = rounding_shift(accumulated, self.hidden_shift).clamp(0, 127)
        accumulated = fixed_multiply(hidden @ self.output_w.T + self.output_b, self.logit_mult)
        return hidden, rounding_shift(accumulated, self.logit_shift).clamp(-128, 127)

    def to_json(self) -> dict[str, Any]:
        return {
            "alphabet": self.alphabet,
            **{name: getattr(self, name).tolist() for name in TENSORS},
            **{name: getattr(self, name) for name in SCALARS},
        }

    def validate(self) -> None:
        vocab = len(self.alphabet)
        if not 2 <= vocab <= 29 or len(set(self.alphabet)) != vocab:
            raise ValueError("alphabet must contain 2..29 unique characters")
        if any(not 32 <= ord(char) <= 126 for char in self.alphabet):
            raise ValueError("alphabet must be printable ASCII")
        scales = (self.embed_scale, self.hidden_w_scale, self.output_scale)
        if any(not 1 <= scale <= 127 for scale in scales):
            raise ValueError("quantization scales must be 1..127")
        if any(not 0 <= s <= 31 for s in (self.hidden_shift, self.logit_shift)):
            raise ValueError("shifts must fit the NPU's five-bit SHIFT field")
        if any(not 0 <= m <= 65535 for m in (self.hidden_mult, self.logit_mult)):
            raise ValueError("multipliers must fit the NPU's 16-bit MULT field")
        if self.embed_w.dim() != 2 or self.embed_w.shape[0] != vocab or not self.embed_size:
            raise ValueError("invalid layer height: embed_w")
        hidden = self.hidden_b.shape[0]
        for name, height, width in (
            ("hidden_w", hidden, self.context_size * self.embed_size),
            ("output_w", vocab, hidden),
        ):
            rows = getattr(self, name)
            if not height or rows.dim() != 2 or rows.shape[0] != height:
                raise ValueError(f"invalid layer height: {name}")
            if rows.shape[1] != width:
                raise ValueError(f"invalid layer width: {name}")
        if self.output_b.shape != (vocab,):
            raise ValueError("invalid layer height: output_b")
        weights = (self.embed_w, self.hidden_w, self.output_w)
        if min(w.min() for w in weights) < -128 or max(w.max() for w in weights) > 127:
            raise ValueError("weights must be signed INT8")
        biases = (self.hidden_b, self.output_b)
        if min(b.min() for b in biases) < -(1 << 31) or max(b.max() for b in biases) >> 31:
            raise ValueError("biases must be signed INT32")


def load_model(path: Path = CHECKPOINT) -> TextModel:
    return TextModel(**json.loads(path.read_text(encoding="utf-8")))


def simple_sentences(italian: str, domain: str) -> list[str]:
    flat = " ".join(italian.split())
    counts = Counter(word.strip(".,") for word in flat.split())
    common = {word for word, _ in counts.most_common(SIMPLE_VOCABULARY)}
    common |= {word.strip(".,") for word in " ".join(domain.split()).split()}
    return [
        sentence
        for sentence in re.split(r"(?<=\.)\s+", flat)
        if 0 < len(sentence) <= SIMPLE_MAX_CHARS
        and all(word.strip(".,") in common for word in sentence.split())
    ]


def load_corpus() -> str:
    domain = (CORPUS_DIR / "domain.txt").read_text(encoding="utf-8")
    italian = (CORPUS_DIR / "italian.txt").read_text(encoding="utf-8")
    kept = simple_sentences(italian, domain)
    return "\n".join([domain] * DOMAIN_REPEATS + ["\n".join(kept)])


def training_examples(corpus: str, alphabet: str, context_size: int) -> Tensor:
    rows = []
    for sentence in re.split(r"(?<=\.)\s+", " ".join(corpus.split())):
        tokens = torch.tensor([alphabet.index(char) for char in " " * context_size + sentence])
        if len(tokens) > context_size:
            rows.append(tokens.unfold(0, context_size + 1, 1))
    return torch.cat(rows)


def corrupt(contexts: Tensor, generator: torch.Generator) -> Tensor:
    if not CONTEXT_NOISE:
        return contexts
    spoiled = torch.rand(contexts.shape, generator=generator) < CONTEXT_NOISE
    return torch.where(
        spoiled, torch.randint(0, len(ALPHABET), contexts.shape, generator=generator), contexts
    )


def train(corpus: str, *, epochs: int = EPOCHS, seed: int = SEED) -> TextModel:
    torch.manual_seed(seed)
    examples = training_examples(corpus, ALPHABET, CONTEXT)
    contexts, targets = examples[:, :-1], examples[:, -1]
    net = CharMLP(len(ALPHABET), CONTEXT, EMBED, HIDDEN)
    optimizer = torch.optim.AdamW(net.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=LEARNING_RATE,
        total_steps=epochs * -(-len(examples) // BATCH),
        pct_start=0.15,
    )
    generator = torch.Generator().manual_seed(seed)
    for epoch in range(epochs):
        for rows in torch.randperm(len(examples), generator=generator).split(BATCH):
            loss = cross_entropy(net(corrupt(contexts[rows], generator)), targets[rows])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            schedule.step()
        LOG.info("epoch %d/%d  loss %.4f", epoch + 1, epochs, loss.item())
    return quantize(net, contexts)


def int8_scale(weights: Tensor) -> int:
    return max(1, min(127, int(127 / max(weights.abs().max().item(), 1e-9))))


def round_int(values: Tensor, scale: float = 1.0) -> Tensor:
    return (values * scale).round().to(torch.int64)


def byte_scale(peak: float) -> tuple[int, int]:
    shift = 0
    while peak / (1 << shift) > 127:
        shift += 1
    if shift:
        shift -= 1
    return shift, min(65535, round(32768 * 127 / max(peak / (1 << shift), 1e-9)))


@torch.no_grad()
def quantize(net: CharMLP, contexts: Tensor) -> TextModel:
    embed_scale, hidden_w_scale, output_scale = (
        int8_scale(layer.weight) for layer in (net.embed, net.hidden, net.output)
    )
    embed_w = round_int(net.embed.weight, embed_scale).clamp(-128, 127)
    hidden_w = round_int(net.hidden.weight, hidden_w_scale).clamp(-128, 127)
    hidden_b = round_int(net.hidden.bias, embed_scale * hidden_w_scale)
    output_w = round_int(net.output.weight, output_scale).clamp(-128, 127)

    calibration = contexts[:: max(1, len(contexts) // CALIBRATION)]
    accumulators = embed_w[calibration].flatten(1) @ hidden_w.T + hidden_b
    hidden_shift, hidden_mult = byte_scale(accumulators.max().item())
    hidden_scale = embed_scale * hidden_w_scale * (hidden_mult / 32768) / (1 << hidden_shift)
    output_b = round_int(net.output.bias, hidden_scale * output_scale)
    hidden = rounding_shift(fixed_multiply(accumulators, hidden_mult), hidden_shift).clamp(0, 127)
    logit_shift, logit_mult = byte_scale((hidden @ output_w.T + output_b).abs().max().item())

    return TextModel(
        alphabet=ALPHABET,
        embed_w=embed_w, hidden_w=hidden_w, hidden_b=hidden_b,
        output_w=output_w, output_b=output_b,
        embed_scale=embed_scale, hidden_w_scale=hidden_w_scale,
        hidden_shift=hidden_shift, hidden_mult=hidden_mult,
        output_scale=output_scale, logit_shift=logit_shift, logit_mult=logit_mult,
    )


def reference_step(model: TextModel, context: list[int]) -> tuple[list[int], list[int], int]:
    vocab = len(model.alphabet)
    if len(context) != model.context_size or any(not 0 <= token < vocab for token in context):
        raise ValueError("invalid context tokens")
    hidden, logits = model(torch.tensor(context))
    return hidden.tolist(), logits.tolist(), int(logits.argmax())


def generate(model: TextModel, prompt: str, count: int = LINE_CHARS) -> str:
    if not 0 <= len(prompt) <= MAX_PROMPT or count < len(prompt):
        raise ValueError("prompt must fit in 24 characters and the output budget")
    size = model.context_size
    context = [model.alphabet.index(char) for char in prompt.rjust(size)[-size:]]
    result = prompt
    for _ in range(count - len(prompt)):
        token = reference_step(model, context)[2]
        result += model.alphabet[token]
        context = context[1:] + [token]
        if model.alphabet[token] == ".":
            break
    return result


def data_line(name: str, values: list[int]) -> str:
    return f"    {name} = {{{{" + ",".join(str(v & 255) for v in values) + "}}"


def compile_weights(model: TextModel) -> str:
    model.validate()
    lines = [
        "# Generated INT8 weights and little-endian INT32 biases. Do not hand-edit.",
        "# Included inside the caller's space section: the embedding table one row",
        "# per dimension, then each dense layer one row per output neuron.",
    ]
    for name, rows, biases in (
        ("embed", model.embed_w.T, None),
        ("hidden", model.hidden_w, model.hidden_b),
        ("output", model.output_w, model.output_b),
    ):
        lines.extend(
            data_line(f"{name}_w" if i == 0 else f"{name}_row_{i}", row)
            for i, row in enumerate(rows.tolist())
        )
        if biases is not None:
            packed = [b for v in biases.tolist() for b in v.to_bytes(4, "little", signed=True)]
            lines.append(data_line(f"{name}_b", packed))
    return "\n".join(lines) + "\n"


def glyph_rows() -> list[int]:
    rom = (HDL_DIR / "text_glyph_rom.sv").read_text(encoding="utf-8")
    glyphs = {
        int(code): int(bits, 16)
        for code, bits in re.findall(r"8'd(\d+): glyph = 35'h([0-9A-Fa-f]+)", rom)
    }
    return [(glyphs[code] >> ((6 - row) * 5)) & 31 for code in range(32, 96) for row in range(7)]


def compile_program(
    model: TextModel,
    prompt: str = "",
    *,
    inline: bool = True,
    weights_include: str = "data/tiny_text_weights.de1",
) -> str:
    model.validate()
    if (
        model.alphabet != ALPHABET
        or model.context_size != CONTEXT
        or model.embed_size != EMBED
        or model.hidden_b.shape[0] != HIDDEN
    ):
        raise ValueError("interactive runtime requires the current model dimensions and alphabet")
    if len(prompt) > MAX_PROMPT or any(c not in model.alphabet for c in prompt):
        raise ValueError("prompt must contain at most 24 supported characters")
    constants = {
        "VOCAB": len(model.alphabet),
        "CONTEXT": CONTEXT,
        "EMBED": EMBED,
        "INPUTS": CONTEXT * EMBED,
        "HIDDEN": HIDDEN,
        "HIDDEN_SHIFT": model.hidden_shift,
        "HIDDEN_MULT": model.hidden_mult,
        "LOGIT_SHIFT": model.logit_shift,
        "LOGIT_MULT": model.logit_mult,
        "LINE_CHARS": LINE_CHARS,
        "MAX_PROMPT": MAX_PROMPT,
        "BG": 0,
        "KEY_BG": 37,
        "SELECTED": 252,
        "WHITE": 255,
        "CYAN": 31,
    }
    strings = {
        "title": "TINY TYPE",
        "hint": "0<  1V  2OK  3>",
        "status_ready": "PRONTO",
        "status_busy": "PENSO ",
        "status_empty": "SCRIVI",
        "status_full": "PIENO ",
        "status_error": "ERRORE",
    }
    lines = [
        "# Generated interactive text terminal. Edit scripts/models/tiny_text/runtime.de1.",
        "# KEY0 left, KEY1 next row, KEY2 select, KEY3 right. Release between presses.",
        *(f"const {name} = {value}" for name, value in constants.items()),
        "",
        "space:",
        data_line("prompt", list(prompt.encode()) + [0] * (MAX_PROMPT + 1 - len(prompt))),
        data_line("prompt_len", [len(prompt)]),
        "    selected: 1",
        "    output_len: 1",
        "    ready: 1",
        "    generation_count: 1",
        "    context: CONTEXT",
        "    embedded: INPUTS",
        "    hidden: HIDDEN",
        "    logits: VOCAB",
        "    generated: LINE_CHARS + 1",
        data_line("alphabet", list(model.alphabet.encode())),
        data_line("key_chars", list(KEYS.encode())),
        *(data_line(name, list(value.encode()) + [0]) for name, value in strings.items()),
        data_line("font", glyph_rows()),
        compile_weights(model) if inline else f'include "{weights_include}"',
        "",
        RUNTIME.read_text(encoding="utf-8"),
    ]
    source = "\n".join(lines)
    if inline and len(assemble(source.splitlines()).to_bytes()) > LOADER_MAX_PROGRAM_SIZE:
        raise ValueError("program exceeds runtime loader capacity")
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true", help="retrain the committed checkpoint")
    parser.add_argument("--run", action="store_true", help="smoke-test with virtual FPGA keys")
    parser.add_argument("--prompt", default="LA CPU", help="prompt for the --run smoke test")
    parser.add_argument("--inline", action="store_true", help="one file, for the web editor")
    parser.add_argument("--epochs", type=int, default=EPOCHS, help="passes over the corpus")
    parser.add_argument("--screenshot", type=Path, help="save the VGA after --run, as a PNG")
    parser.add_argument("-o", type=Path, default=PROGRAM)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    LOG.setLevel(logging.INFO)

    if args.train:
        model = train(load_corpus(), epochs=args.epochs)
        CHECKPOINT.write_text(json.dumps(model.to_json(), indent=2) + "\n", encoding="utf-8")
    else:
        model = load_model()
    if not args.inline:
        weights_path = args.o.parent / "data" / WEIGHTS.name
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        weights_path.write_text(compile_weights(model), encoding="utf-8")

    source = compile_program(model, inline=args.inline)
    args.o.write_text(source, encoding="utf-8")
    program = assemble(source.splitlines(), args.o.parent)
    LOG.info(
        "Exported %s: %d bytes, %d characters in vocabulary",
        args.o,
        len(program.to_bytes()),
        len(model.alphabet),
    )
    if args.run:
        from scripts.ml.simulate import smoke_test

        text, steps = smoke_test(model, program, args.prompt, args.screenshot)
        LOG.info("%s", text)
        LOG.info("Completed in %d architectural steps (not RTL clock cycles)", steps)


if __name__ == "__main__":
    main()
