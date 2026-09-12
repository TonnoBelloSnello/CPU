"""Download public-domain Italian prose and fold it onto the demo's alphabet.

`corpus/domain.txt` is hand-written and teaches the demo what to say about this
CPU; it is far too small to teach it how Italian is spelled. This fetches
narrative prose from Project Gutenberg, normalises it into the same
29-character alphabet the NPU model uses, and writes `corpus/italian.txt` plus a
held-out `corpus/italian_validation.txt`.

Verse and pre-modern Italian are excluded on purpose: Dante and Boccaccio would
teach spellings that no longer exist. Every work is public domain in its country
of origin and in the United States. Project Gutenberg's licence covers its
boilerplate and trademark, not the works; the boilerplate is stripped here and
no trademark is redistributed, which is what that licence asks of unlicensed use.

    uv run python scripts/ml/fetch_corpus.py

Network access is required, so this is a manual step like `--train`, not part of
the test suite. The files it writes are committed.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = ROOT / "scripts" / "models" / "tiny_text" / "corpus"
TRAIN_OUT = CORPUS_DIR / "italian.txt"
VALIDATION_OUT = CORPUS_DIR / "italian_validation.txt"

LOG = logging.getLogger(__name__)

ALPHABET = frozenset(" ,.ABCDEFGHIJKLMNOPQRSTUVWXYZ")

BOOKS = (
    (61885, "Ricordi d'infanzia e di scuola", "De Amicis"),
    (61209, "I Robinson italiani", "Salgari"),
    (70993, "L'Uomo di Fuoco", "Salgari"),
    (58415, "Una sfida al Polo", "Salgari"),
    (22504, "Il mistero del poeta", "Fogazzaro"),
    (22020, "L'indomani", "Neera"),
    (25178, "Damiano: storia di una povera famiglia", "Carcano"),
)
TEXT_URLS = (
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://www.gutenberg.org/files/{id}/{id}.txt",
    "https://www.gutenberg.org/files/{id}/{id}-8.txt",
)

MIN_SENTENCE = 25
MAX_SENTENCE = 160
MIN_WORDS = 4
VALIDATION_SENTENCES = 100
SEED = 42

TO_SPACE = "'\u2018\u2019\u02bc\u00ab\u00bb\u201c\u201d\"()[]{}*_/\\|@#%&+=<>~^`\u2013\u2014-"
TO_COMMA = ";:"
TO_PERIOD = "!?\u2026"
FOLD = (
    {ord(c): " " for c in TO_SPACE}
    | {ord(c): "," for c in TO_COMMA}
    | {ord(c): "." for c in TO_PERIOD}
)


def download(book_id: int, timeout: float = 120.0) -> str:
    last: OSError | None = None
    for template in TEXT_URLS:
        request = urllib.request.Request(
            template.format(id=book_id), headers={"User-Agent": "cpu-tiny-text/1.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except OSError as error:
            last = error
            continue
        for encoding in ("utf-8", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
    raise last if last is not None else OSError("no candidate URL")


def strip_boilerplate(text: str) -> str:
    if start := re.search(r"\*\*\*\s*START OF TH[EI][^*]*\*\*\*", text):
        text = text[start.end() :]
    if end := re.search(r"\*\*\*\s*END OF TH[EI][^*]*\*\*\*", text):
        text = text[: end.start()]
    return text


def normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper().translate(FOLD)


def sentences(text: str) -> list[str]:
    kept = []
    for raw in re.split(r"(?<=\.)", normalise(text)):
        sentence = re.sub(r"\s+([.,])", r"\1", " ".join(raw.split()))
        sentence = re.sub(r",+", ",", sentence).strip(" ,")
        if (
            sentence.endswith(".")
            and sentence.count(".") == 1
            and set(sentence) <= ALPHABET
            and MIN_SENTENCE <= len(sentence) <= MAX_SENTENCE
            and len(sentence.split()) >= MIN_WORDS
        ):
            kept.append(sentence)
    return kept


def collect(books: tuple[tuple[int, str, str], ...] = BOOKS) -> list[str]:
    collected: list[str] = []
    seen: set[str] = set()
    for book_id, title, author in books:
        try:
            text = download(book_id)
        except OSError as error:
            LOG.warning("skipping %s (%s): %s", title, book_id, error)
            continue
        found = [s for s in sentences(strip_boilerplate(text)) if s not in seen]
        seen.update(found)
        collected.extend(found)
        LOG.info("%-40s %-12s %6d sentences", title[:40], author, len(found))
    return collected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--train-out", type=Path, default=TRAIN_OUT)
    parser.add_argument("--validation-out", type=Path, default=VALIDATION_OUT)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    collected = collect()
    if not collected:
        LOG.error("no text could be downloaded")
        return 1

    random.Random(SEED).shuffle(collected)
    cut = min(VALIDATION_SENTENCES, len(collected) // 2)
    for path, group in ((args.train_out, collected[cut:]), (args.validation_out, collected[:cut])):
        path.write_text("\n".join(group) + "\n", encoding="utf-8")
        characters = sum(len(sentence) + 1 for sentence in group)
        LOG.info("%s: %d sentences, %d characters", path.name, len(group), characters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
