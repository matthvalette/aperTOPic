"""Labelled evaluation samples built from the hackapertus files.

Documents are built with the same section logic the API uses, so the evaluation measures the
production path: title, submitted text and reasoning of a federal affair in one language.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from ..adapters.openparldata import TEXT_KINDS, clean_text
from ..domain.models import SourceDocument, SourceKind, TextBlock
from ..services.documents import sections_from_texts

LANGUAGES = ("de", "fr", "it")


@dataclass
class LabelledAffair:
    affair_id: int
    number: str
    year: int
    type: str
    gold: set[str]
    blocks: list[TextBlock] = field(default_factory=list)

    @property
    def split(self) -> str:
        """Stable 50/50 split: thresholds are tuned on dev and reported on test."""
        digest = hashlib.sha1(str(self.affair_id).encode()).digest()
        return "dev" if digest[0] % 2 == 0 else "test"

    def document(self, language: str) -> SourceDocument:
        sections, chosen = sections_from_texts(self.blocks, language)
        return SourceDocument(
            kind=SourceKind.AFFAIR,
            reference=str(self.affair_id),
            title=sections.get("title"),
            body_key="CHE",
            affair_type=self.type,
            language=chosen,
            sections=sections,
        )

    def has_texts(self, languages: tuple[str, ...]) -> bool:
        have = {(b.kind, b.language) for b in self.blocks}
        return all(("submitted_text", lang) in have for lang in languages)


def _read_affairs(data_dir: Path) -> list[dict]:
    with (data_dir / "che_affairs_keywords.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def attach_texts(data_dir: Path, affairs: dict[int, LabelledAffair]) -> None:
    """Stream the 240 MB texts file once and keep only the sampled affairs' texts."""
    with gzip.open(data_dir / "che_affair_texts.ndjson.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            affair = affairs.get(row["openparldata_id"])
            if affair is None:
                continue
            kind = TEXT_KINDS.get(row.get("type_de") or "", row.get("type_de") or "text")
            for lang in LANGUAGES:
                text = clean_text(row.get(f"text_{lang}"))
                if text:
                    affair.blocks.append(TextBlock(kind=kind, language=lang, text=text))


def subject_area_sample(
    data_dir: Path,
    *,
    n: int,
    years: tuple[int, int] = (2018, 2026),
    seed: int = 7,
    require_languages: tuple[str, ...] = LANGUAGES,
) -> list[LabelledAffair]:
    """Federal affairs with Curia Vista subject areas and a submitted text in every language."""
    population = []
    for row in _read_affairs(data_dir):
        year = int((row.get("begin_date") or "0")[:4] or 0)
        if not row.get("topic_ids") or not (years[0] <= year <= years[1]):
            continue
        population.append(
            LabelledAffair(
                affair_id=row["openparldata_id"],
                number=row["number"],
                year=year,
                type=row.get("type_en") or row.get("type_de") or "",
                gold={str(t) for t in row["topic_ids"]},
            )
        )
    rng = random.Random(seed)
    rng.shuffle(population)
    candidates = {a.affair_id: a for a in population[: n * 3]}
    attach_texts(data_dir, candidates)
    ordered = [a for a in population[: n * 3] if a.has_texts(require_languages)]
    return ordered[:n]


def digitalisation_sample(
    data_dir: Path, *, n: int, years: tuple[int, int] = (2019, 2023), seed: int = 7
) -> tuple[list[LabelledAffair], list[LabelledAffair]]:
    """Federal affairs tagged "Digitalisierung" by PolitMonitor, and untagged ones from the same years.

    2019 to 2023 are the years PolitMonitor tagged consistently. Untagged affairs are treated
    as negatives, although editors may have missed some, so precision is a lower bound.
    """
    with (data_dir / "politmonitor_digitalisierung.csv").open(encoding="utf-8") as handle:
        tagged = {int(r["openparldata_id"]) for r in csv.DictReader(handle) if r["body_key"] == "CHE"}
    positives, negatives = [], []
    for row in _read_affairs(data_dir):
        year = int((row.get("begin_date") or "0")[:4] or 0)
        if not (years[0] <= year <= years[1]):
            continue
        affair = LabelledAffair(
            affair_id=row["openparldata_id"],
            number=row["number"],
            year=year,
            type=row.get("type_en") or row.get("type_de") or "",
            gold={"digitalisation"} if row["openparldata_id"] in tagged else set(),
        )
        (positives if affair.gold else negatives).append(affair)
    rng = random.Random(seed)
    rng.shuffle(positives)
    rng.shuffle(negatives)
    half = n // 2
    candidates = {a.affair_id: a for a in positives[: half * 2] + negatives[: half * 2]}
    attach_texts(data_dir, candidates)
    pos = [a for a in positives[: half * 2] if a.has_texts(("de",))][:half]
    neg = [a for a in negatives[: half * 2] if a.has_texts(("de",))][:half]
    return pos, neg
