"""TypeSafe Jev: topic probabilities and search relevance.

Implements `TopicClassifier` and `RelevanceRanker`.

Question design, following the TypeSafe docs:
- Multi-label scheme (Curia Vista subject areas, ad-hoc topics): one Noul per topic, because
  several topics may apply. The noul is the probability that the topic applies.
- Single-label scheme (St. Gallen, Thurgau): one Choice over all topics. Its probabilities
  compare the topics with each other and sum to 1.
- Binary topic (digitalisation): one Noul.
All taxonomies requested for a document go into one request: the state is read once and the
questions are answered in parallel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, NoulCriteria

from ..domain.models import (
    AffairSummary,
    Classification,
    SourceDocument,
    Taxonomy,
    TaxonomyKind,
    Topic,
    TopicScore,
)

# Section order in the state, most informative first. Unknown sections follow.
SECTION_ORDER = ("title", "lead", "submitted_text", "reasoning", "answer", "document")

TOPIC_QUESTION = (
    "Is one of the main subjects of the parliamentary affair in `affair` covered by `subject_area`?"
)
TOPIC_CRITERIA = NoulCriteria(
    true="The subject area covers the affair's main subject or one of its main subjects. An affair "
    "often has one to three main subjects.",
    false="None of the affair's main subjects falls under this subject area. It is unrelated or only "
    "mentioned in passing.",
)
ADHOC_QUESTION = "Is the parliamentary affair in `affair` about `topic`?"
ADHOC_CRITERIA = NoulCriteria(
    true="Dealing with the topic is a main purpose of the affair.",
    false="The affair is about something else. The topic is absent or only mentioned in passing.",
)
CHOICE_QUESTION = (
    "Which subject area does the parliamentary affair in `affair` belong to? Pick the area that "
    "covers its main subject."
)
RELEVANCE_QUESTION = "Is the parliamentary affair `affair` about what `search_request` asks for?"
RELEVANCE_CRITERIA = NoulCriteria(
    true="The affair's subject matches the search request.",
    false="The affair is about a different subject, even if it shares a word with the request.",
)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut[: cut.rfind(" ")] + " […]" if " " in cut else cut


def build_state(document: SourceDocument, *, max_section_chars: int, max_state_chars: int) -> dict[str, Any]:
    """The affair as named fields, with long sections cut so the state stays focused."""
    affair: dict[str, Any] = {}
    if document.body_key:
        affair["parliament"] = document.body_key
    if document.affair_type:
        affair["type"] = document.affair_type
    if document.title and "title" not in document.sections:
        affair["title"] = document.title
    ordered = sorted(
        document.sections.items(),
        key=lambda kv: SECTION_ORDER.index(kv[0]) if kv[0] in SECTION_ORDER else len(SECTION_ORDER),
    )
    budget = max_state_chars
    for name, text in ordered:
        if budget <= 0:
            break
        piece = truncate(text, min(max_section_chars, budget))
        affair[name] = piece
        budget -= len(piece)
    return {"affair": affair}


def _topic_payload(topic: Topic) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": topic.name}
    others = {k: v for k, v in topic.names.items() if v and v != topic.name}
    if others:
        payload["also_called"] = others
    if topic.description:
        payload["covers"] = topic.description
    return payload


def build_questions(taxonomy: Taxonomy, prefix: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Questions for one taxonomy, and the map from question id back to topic id."""
    questions: dict[str, Any] = {}
    to_topic: dict[str, str] = {}
    if taxonomy.kind is TaxonomyKind.SINGLE_LABEL:
        options = {topic.name: topic.description for topic in taxonomy.topics}
        questions[f"{prefix}choice"] = Choice(instructions=CHOICE_QUESTION, criteria=options)
        return questions, to_topic
    adhoc = taxonomy.kind is TaxonomyKind.BINARY or taxonomy.id == "custom"
    for index, topic in enumerate(taxonomy.topics):
        qid = f"{prefix}t{index:03d}"
        key = "topic" if adhoc else "subject_area"
        questions[qid] = Noul(
            instructions={key: _topic_payload(topic), "question": ADHOC_QUESTION if adhoc else TOPIC_QUESTION},
            criteria=ADHOC_CRITERIA if adhoc else TOPIC_CRITERIA,
        )
        to_topic[qid] = topic.id
    return questions, to_topic


class JevTopicClassifier:
    def __init__(
        self,
        client: AsyncTypeSafeClient,
        *,
        model: str,
        max_concurrency: int = 8,
        max_section_chars: int = 6000,
        max_state_chars: int = 16000,
    ) -> None:
        self._client = client
        self.model = model
        self._limit = asyncio.Semaphore(max_concurrency)
        self._max_section_chars = max_section_chars
        self._max_state_chars = max_state_chars
        self.requests = 0
        self.input_tokens = 0  # running totals, for cost estimates

    async def classify(
        self, document: SourceDocument, taxonomies: Sequence[Taxonomy], *, threshold: float | None = None
    ) -> list[Classification]:
        state = build_state(
            document, max_section_chars=self._max_section_chars, max_state_chars=self._max_state_chars
        )
        questions: dict[str, Any] = {}
        maps: list[tuple[Taxonomy, str, dict[str, str]]] = []
        for index, taxonomy in enumerate(taxonomies):
            prefix = f"x{index}_"
            qs, to_topic = build_questions(taxonomy, prefix)
            questions.update(qs)
            maps.append((taxonomy, prefix, to_topic))
        async with self._limit:
            response = await self._client.system_one(state=state, questions=questions, model=self.model)
        self.requests += 1
        self.input_tokens += response.usage.input_tokens if response.usage else 0
        return [
            self._read(taxonomy, prefix, to_topic, response, taxonomy.default_threshold if threshold is None else threshold)
            for taxonomy, prefix, to_topic in maps
        ]

    @staticmethod
    def _read(taxonomy: Taxonomy, prefix: str, to_topic: dict[str, str], response: Any, threshold: float) -> Classification:
        if taxonomy.kind is TaxonomyKind.SINGLE_LABEL:
            answer = response.choices[f"{prefix}choice"]
            by_name = {t.name: t for t in taxonomy.topics}
            scores = [
                TopicScore(topic_id=by_name[name].id, name=name, probability=float(p))
                for name, p in answer.probabilities.items()
                if name in by_name
            ]
            scores.sort(key=lambda s: s.probability, reverse=True)
            return Classification(
                taxonomy_id=taxonomy.id,
                kind=taxonomy.kind,
                scores=scores,
                predicted=[by_name[answer.choice].id] if answer.choice in by_name else [],
                confidence=answer.confidence,
                model=response.model,
            )
        scores = []
        groups: dict[str, float] = {}
        for qid, topic_id in to_topic.items():
            topic = taxonomy.topic(topic_id)
            probability = float(response.nouls[qid].noul)
            scores.append(TopicScore(topic_id=topic_id, name=topic.name, probability=probability))
            if topic.group:
                groups[topic.group] = max(groups.get(topic.group, 0.0), probability)
        scores.sort(key=lambda s: s.probability, reverse=True)
        return Classification(
            taxonomy_id=taxonomy.id,
            kind=taxonomy.kind,
            scores=scores,
            predicted=[s.topic_id for s in scores if s.probability >= threshold],
            threshold=threshold,
            groups=sorted(
                (TopicScore(topic_id=g, name=g, probability=p) for g, p in groups.items()),
                key=lambda s: s.probability,
                reverse=True,
            ),
            model=response.model,
        )


class JevRelevanceRanker:
    """One Noul per candidate, batched: the request goes in the state, each affair in its question."""

    def __init__(self, client: AsyncTypeSafeClient, *, model: str, batch_size: int = 40) -> None:
        self._client = client
        self.model = model
        self._batch_size = batch_size

    async def _score_batch(self, request: str, affairs: Sequence[AffairSummary]) -> list[float]:
        questions = {
            f"c{i:03d}": Noul(
                instructions={
                    "affair": {
                        "title": affair.best_title(),
                        "parliament": affair.body_key,
                        "type": affair.type.get("en") or affair.type.get("de"),
                        "date": affair.begin_date.isoformat() if affair.begin_date else None,
                    },
                    "question": RELEVANCE_QUESTION,
                },
                criteria=RELEVANCE_CRITERIA,
            )
            for i, affair in enumerate(affairs)
        }
        response = await self._client.system_one(
            state={"search_request": request}, questions=questions, model=self.model
        )
        return [float(response.nouls[f"c{i:03d}"].noul) for i in range(len(affairs))]

    async def score(self, request: str, affairs: Sequence[AffairSummary]) -> list[float]:
        batches = [affairs[i : i + self._batch_size] for i in range(0, len(affairs), self._batch_size)]
        results = await asyncio.gather(*(self._score_batch(request, b) for b in batches))
        return [score for batch in results for score in batch]
