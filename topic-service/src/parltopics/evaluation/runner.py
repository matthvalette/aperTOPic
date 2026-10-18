"""Runs a classifier over labelled documents, with a disk cache so reruns cost nothing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..adapters import jev as jev_questions
from ..domain.models import SourceDocument, Taxonomy
from ..domain.ports import TopicClassifier


def fingerprint(taxonomy: Taxonomy) -> str:
    """Changes whenever the questions sent to Jev change, which invalidates cached answers."""
    parts = [
        taxonomy.kind.value,
        json.dumps([topic.model_dump() for topic in taxonomy.topics], sort_keys=True, ensure_ascii=False),
        jev_questions.TOPIC_QUESTION,
        jev_questions.ADHOC_QUESTION,
        jev_questions.CHOICE_QUESTION,
        repr(jev_questions.TOPIC_CRITERIA),
        repr(jev_questions.ADHOC_CRITERIA),
    ]
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:12]


def document_key(document: SourceDocument) -> str:
    body = json.dumps(document.sections, sort_keys=True, ensure_ascii=False)
    return f"{document.reference}:{document.language}:{hashlib.sha1(body.encode()).hexdigest()[:10]}"


class PredictionCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._data[row["key"]] = row["value"]

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"key": key, "value": value}, ensure_ascii=False) + "\n")


@dataclass
class RunStats:
    requested: int = 0
    cached: int = 0
    failed: list[str] = field(default_factory=list)
    seconds: float = 0.0


async def predict(
    documents: list[SourceDocument],
    taxonomy: Taxonomy,
    classifier: TopicClassifier,
    cache: PredictionCache,
    *,
    model: str,
    label: str = "",
) -> tuple[dict[str, dict[str, float]], RunStats]:
    """Probabilities per document reference, for every topic of the taxonomy."""
    stats = RunStats()
    prefix = f"{model}|{fingerprint(taxonomy)}|"
    results: dict[str, dict[str, float]] = {}
    pending: list[SourceDocument] = []
    for document in documents:
        hit = cache.get(prefix + document_key(document))
        if hit is not None:
            results[document.reference or ""] = hit
            stats.cached += 1
        else:
            pending.append(document)

    done = 0
    started = time.perf_counter()

    async def one(document: SourceDocument) -> None:
        nonlocal done
        try:
            [classification] = await classifier.classify(document, [taxonomy], threshold=0.5)
        except Exception as error:  # keep going; failures are reported
            stats.failed.append(f"{document.reference}: {type(error).__name__}: {error}")
            return
        probs = {s.topic_id: s.probability for s in classification.scores}
        cache.put(prefix + document_key(document), probs)
        results[document.reference or ""] = probs
        stats.requested += 1
        done += 1
        if done % 50 == 0:
            print(f"  {label} {done}/{len(pending)} classified", flush=True)

    await asyncio.gather(*(one(d) for d in pending))
    stats.seconds = time.perf_counter() - started
    return results, stats
