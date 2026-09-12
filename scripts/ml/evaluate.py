"""Score a tiny_text checkpoint the way docs/tiny-text.md ranks candidates.

Next-character accuracy is the number that is easy to measure and the one that
ranks generations wrongly: it is graded against the true continuation one
character at a time, while generation feeds the model its own output and
compounds its own errors. The three measures over whole completions are what
the corpus settings and the training recipe were actually chosen on, so they
belong in a script rather than in a paragraph nobody can re-run:

* **terminated** -- completions that reach a period instead of the line limit;
* **invented** -- words in no corpus, the rate that says whether it still spells;
* **repeated** -- words echoing one of the three before them, the loop failure.

Prompts are the first two words of each held-out sentence, so the model is asked
to finish a sentence it has never seen while every prompt is one a person might
plausibly type.

    uv run python scripts/ml/evaluate.py                       # committed checkpoint
    uv run python scripts/ml/evaluate.py --checkpoint other.json
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ml.tiny_text import (  # noqa: E402
    CHECKPOINT,
    CORPUS_DIR,
    LINE_CHARS,
    TextModel,
    generate,
    load_model,
    training_examples,
)

LOG = logging.getLogger(__name__)

BOOK_PROMPTS = 100
REPETITION_WINDOW = 3


def words(text: str) -> list[str]:
    return [word.strip(".,") for word in text.split() if word.strip(".,")]


def known_words() -> frozenset[str]:
    text = " ".join(
        (CORPUS_DIR / name).read_text(encoding="utf-8")
        for name in ("domain.txt", "italian.txt", "domain_validation.txt")
    )
    return frozenset(words(text))


def sentences(name: str) -> list[str]:
    flat = " ".join((CORPUS_DIR / name).read_text(encoding="utf-8").split())
    return [sentence for sentence in re.split(r"(?<=\.)\s+", flat) if sentence]


def prompts(name: str, limit: int | None = None) -> list[str]:
    starts = [
        " ".join(sentence.split()[:2]).strip(".,")
        for sentence in sentences(name)
        if len(sentence.split()) >= 3
    ]
    return starts[:limit] if limit else starts


def accuracy(model: TextModel, name: str) -> tuple[float, int]:
    examples = training_examples(
        (CORPUS_DIR / name).read_text(encoding="utf-8"), model.alphabet, model.context_size
    )
    _, logits = model(examples[:, :-1])
    return float((logits.argmax(1) == examples[:, -1]).sum()) / len(examples), len(examples)


def completions(
    model: TextModel, starts: list[str], vocabulary: frozenset[str]
) -> dict[str, float]:
    ended = invented = repeated = counted = 0
    for prompt in starts:
        text = generate(model, prompt, LINE_CHARS)
        ended += text.endswith(".")
        history = words(prompt)
        for word in words(text[len(prompt) :]):
            counted += 1
            invented += word not in vocabulary
            repeated += word in history[-REPETITION_WINDOW:]
            history.append(word)
    return {
        "terminated": 100.0 * ended / max(1, len(starts)),
        "invented": 100.0 * invented / max(1, counted),
        "repeated": 100.0 * repeated / max(1, counted),
        "prompts": len(starts),
        "words": counted,
    }


def report(model: TextModel) -> dict[str, dict[str, float]]:
    vocabulary = known_words()
    results: dict[str, dict[str, float]] = {}
    for label, validation, limit in (
        ("domain", "domain_validation.txt", None),
        ("book", "italian_validation.txt", BOOK_PROMPTS),
    ):
        correct, examples = accuracy(model, validation)
        results[label] = {
            "accuracy": 100.0 * correct,
            "examples": examples,
            **completions(model, prompts(validation, limit), vocabulary),
        }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument(
        "--prompt", action="append", default=[], help="also generate from this prompt"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    model = load_model(args.checkpoint)
    for label, scores in report(model).items():
        LOG.info(
            "%-6s accuracy %5.2f%% of %d   terminated %5.1f%%   invented %4.1f%%   "
            "repeated %4.1f%%   (%d prompts, %d words)",
            label,
            scores["accuracy"],
            scores["examples"],
            scores["terminated"],
            scores["invented"],
            scores["repeated"],
            scores["prompts"],
            scores["words"],
        )
    for prompt in args.prompt:
        LOG.info("%s", generate(model, prompt))


if __name__ == "__main__":
    main()
