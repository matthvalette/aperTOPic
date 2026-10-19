"""Labels people gave to affairs, from the labelled data in files.openparldata.ch/hackapertus.

Implements `LabelLookup`. Loaded once into memory (about 0.3 s):
- federal affairs: the Curia Vista subject areas of the Parliamentary Services,
- St. Gallen, Thurgau, the city of Zug and Zurich: their own classification,
- the PolitMonitor "Digitalisierung" tag behind the DVS list.
A label carries `taxonomy_id` and `topic_id` when it is a topic of one of the service's label sets, so it
can be compared with a classification. Others (Zug departments, Zurich free keywords) are shown as text.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from ..domain.models import KnownLabel
from ..domain.ports import TaxonomyProvider
from .taxonomies import CURIA, DIGITALISATION, SG, TG, slugify

log = logging.getLogger(__name__)

CURIA_SOURCE = "Parliamentary Services (Curia Vista)"
POLITMONITOR_SOURCE = "PolitMonitor editors (DVS list)"
CANTONAL = {
    "SG": (SG, "Kantonsrat St. Gallen"),
    "TG": (TG, "Grosser Rat Thurgau"),
    "1711": (None, "Stadt Zug, responsible department"),
    "ZH": (None, "Kanton Zürich, keywords"),
}


class LabelledDataLabels:
    def __init__(self, data_dir: Path, taxonomies: TaxonomyProvider | None = None) -> None:
        self._known_topics: dict[str, set[str]] = {}
        if taxonomies is not None:
            self._known_topics = {t.id: {topic.id for topic in t.topics} for t in taxonomies.list()}
        self._names: dict[tuple[str, str], str] = {}
        if taxonomies is not None:
            for taxonomy in taxonomies.list():
                for topic in taxonomy.topics:
                    self._names[(taxonomy.id, topic.id)] = topic.name
        self._by_affair: dict[int, list[KnownLabel]] = {}
        self._load_federal(data_dir / "che_affairs_keywords.jsonl")
        self._load_cantonal(data_dir / "cantonal_affairs_keywords.jsonl")
        self._load_politmonitor(data_dir / "politmonitor_digitalisierung.csv")

    def __len__(self) -> int:
        return len(self._by_affair)

    def labels(self, affair_ids: Sequence[int]) -> dict[int, list[KnownLabel]]:
        return {i: self._by_affair[i] for i in affair_ids if i in self._by_affair}

    # ---------- loading ----------

    def _label(self, taxonomy_id: str | None, topic_id: str | None, name: str, source: str) -> KnownLabel:
        """Keep the taxonomy link only for topics the label set really has; use the label set's topic name."""
        if taxonomy_id and topic_id and topic_id in self._known_topics.get(taxonomy_id, ()):
            return KnownLabel(
                taxonomy_id=taxonomy_id, topic_id=topic_id, name=self._names.get((taxonomy_id, topic_id), name), source=source
            )
        return KnownLabel(name=name, source=source)

    def _add(self, affair_id: int, label: KnownLabel) -> None:
        labels = self._by_affair.setdefault(affair_id, [])
        if all((l.taxonomy_id, l.topic_id, l.name) != (label.taxonomy_id, label.topic_id, label.name) for l in labels):
            labels.append(label)

    def _load_federal(self, path: Path) -> None:
        if not path.exists():
            log.warning("No federal labels: %s is missing", path)
            return
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                ids, names = row.get("topic_ids") or [], row.get("topics_de") or []
                for index, topic_id in enumerate(ids):
                    name = names[index] if index < len(names) else str(topic_id)
                    self._add(int(row["openparldata_id"]), self._label(CURIA, str(topic_id), name, CURIA_SOURCE))

    def _load_cantonal(self, path: Path) -> None:
        if not path.exists():
            log.warning("No cantonal labels: %s is missing", path)
            return
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                taxonomy_id, source = CANTONAL.get(str(row.get("body_key")), (None, str(row.get("body_name") or "")))
                keywords = row.get("keywords") or []
                codes = row.get("keyword_codes") or []
                for index, keyword in enumerate(keywords):
                    code = codes[index] if len(codes) == len(keywords) else None
                    topic_id = (code or slugify(keyword)) if taxonomy_id else None
                    name = f"{code} {keyword}" if code else keyword
                    self._add(int(row["openparldata_id"]), self._label(taxonomy_id, topic_id, name, source))

    def _load_politmonitor(self, path: Path) -> None:
        if not path.exists():
            log.warning("No PolitMonitor tags: %s is missing", path)
            return
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("openparldata_id"):
                    self._add(
                        int(row["openparldata_id"]),
                        self._label(DIGITALISATION, "digitalisation", "Digitalisierung", POLITMONITOR_SOURCE),
                    )
