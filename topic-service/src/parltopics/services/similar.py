"""Similar cases: affairs in any parliament and language on the same subject as a document.

    document ──Apertus──▶ title words per language ──OpenParlData──▶ hits per word or word pair
             ──same titles grouped──▶ Jev similarity to the document ──▶ cases with the labels people gave them

The search needs every query word in a title and returns the newest hits first, so queries are built from
single words by how many titles each matches, not written as phrases:
- a word matching at most 60 titles is specific: searched on its own, all its hits are kept;
- the first two words name the subject: searched on their own even when broader (newest 30 hits);
- broad words among the first four are also paired with each other.
Chosen on 42 documents (20 dev, 22 held-out test) against six alternatives. On the test half, 79% of the
five cases shown first deal with the same issue (Jev judgment, checked by hand), against 10% when the
document is first summarised into a request for the /search translator.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field

from ..domain.models import (
    PARLIAMENT_LANGUAGES,
    AffairSummary,
    DocumentKeywords,
    KnownLabel,
    QueryMatch,
    SourceDocument,
)
from ..domain.ports import AffairSearchEngine, KeywordWriter, LabelLookup, SimilarityRanker
from .classify import DocumentInfo

log = logging.getLogger(__name__)

# Words that only say what kind of document or polity it is. They match thousands of titles.
PROCEDURAL = {
    "motion", "motionen", "postulat", "postulate", "interpellation", "interpellanza", "anfrage", "frage", "fragen",
    "question", "questions", "interrogazione", "dumonda", "incumbensa", "bericht", "rapport", "rapporto", "antwort",
    "réponse", "risposta", "kanton", "kantone", "kantons", "canton", "cantons", "cantone", "cantoni", "chantun", "bund",
    "confédération", "confederazione", "schweiz", "suisse", "svizzera", "svizra", "gemeinde", "gemeinden", "commune",
    "communes", "comune", "comuni", "vischnanca", "parlament", "parlement", "parlamento", "regierung", "regierungsrat",
    "gouvernement", "governo", "conseil", "consiglio", "bundesrat", "situation", "situazione",
}
WORDS_PER_LANGUAGE = 8
SINGLE_MAX = 60  # a word matching at most this many titles is specific enough on its own
CORE_WORDS = 2  # the first words name the subject: searched alone even when broad...
CORE_LIMIT = 30  # ...keeping their newest hits
PAIR_WORDS = 4  # broad words among the first four are paired
MAX_PAIRS = 5  # per language
PAIR_LIMIT = 30
MAX_RANKED = 240  # candidates sent to Jev; above this the most specific matches are kept

# Function words for guessing a text's language when Apertus is unavailable.
_STOPWORDS = {
    "de": {"der", "die", "und", "das", "nicht", "mit", "ist", "für", "auf", "dem", "werden", "eine", "zu", "von"},
    "fr": {"le", "les", "et", "des", "est", "une", "pour", "dans", "que", "du", "pas", "sur", "au", "qui"},
    "it": {"il", "della", "che", "di", "per", "non", "una", "sono", "nel", "dei", "gli", "anche", "come", "alla"},
    "rm": {"ils", "dal", "cun", "ina", "betg", "vegn", "dals", "las", "sco", "tar", "era", "nua", "quai", "vegnan"},
}


class SimilarOptions(BaseModel):
    languages: list[str] = Field(default_factory=lambda: list(PARLIAMENT_LANGUAGES))
    max_results: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(
        default=0.25, ge=0, le=1, description="When ranking, hide cases Jev rates below this similarity."
    )
    rank: bool = Field(default=True, description="Order the cases by Jev similarity to the document")
    body_keys: list[str] = Field(default_factory=list, description="Limit to parliaments, e.g. CHE, BE, 261")


class SimilarQuery(BaseModel):
    language: str
    query: str
    hits: int = Field(description="Affairs the query returned; 61 means more than 60 (a broad word).")


class SimilarCase(BaseModel):
    affair: AffairSummary
    similarity: float | None = Field(
        default=None, description="Jev probability that the affair deals with the same specific issue."
    )
    matched_by: list[QueryMatch] = Field(default_factory=list)
    labels: list[KnownLabel] = Field(
        default_factory=list, description="Labels people gave the affair or an affair with the same title."
    )
    same_title: list[AffairSummary] = Field(
        default_factory=list,
        description="Other affairs of the same parliament with the same title (identical motions, resubmissions).",
    )


class TopicHint(BaseModel):
    """A label the similar cases carry, weighted by how similar each case is."""

    taxonomy_id: str | None
    topic_id: str | None
    name: str
    source: str
    cases: int
    weight: float = Field(description="Sum of the similarities of the cases with this label.")
    affair_ids: list[int]


class SimilarOutcome(BaseModel):
    document: DocumentInfo
    subject: str | None = Field(description="The document's subject as Apertus read it.")
    keywords: dict[str, list[str]] = Field(description="The title words Apertus chose, per language.")
    queries: list[SimilarQuery]
    cases: list[SimilarCase]
    topics: list[TopicHint] = Field(description="Labels of the cases shown, most weight first.")
    candidates: int = Field(description="Distinct affairs found before ranking (same titles counted once).")
    ranked: bool
    warnings: list[str] = Field(default_factory=list)


@dataclass
class _Group:
    """Affairs of one parliament with the same title."""

    members: list[AffairSummary] = field(default_factory=list)
    matched_by: list[QueryMatch] = field(default_factory=list)
    specificity: float = 0.0  # used to order when there is no ranking
    similarity: float | None = None

    @property
    def representative(self) -> AffairSummary:
        return max(self.members, key=lambda a: (a.begin_date or date.min, a.id))


def _group_key(affair: AffairSummary) -> tuple[str, str]:
    return affair.body_key, " ".join(affair.best_title().lower().split())


def guess_language(text: str, languages: Sequence[str]) -> str:
    words = [w.strip(".,;:()«»\"'").lower() for w in text.split()[:3000]]
    scores = {lang: sum(1 for w in words if w in _STOPWORDS.get(lang, ())) for lang in languages}
    return max(scores, key=scores.get) if scores else "de"


def title_words(title: str, limit: int = 4) -> list[str]:
    """Fallback without Apertus: the longest distinctive words of the title."""
    words = []
    for raw in title.split():
        word = raw.strip(".,;:!?()«»\"'“”„")
        if len(word) >= 5 and word.lower() not in PROCEDURAL and word.lower() not in {w.lower() for w in words}:
            words.append(word)
    return sorted(words, key=len, reverse=True)[:limit]


def topic_hints(cases: Sequence[SimilarCase]) -> list[TopicHint]:
    hints: dict[tuple[str | None, str], TopicHint] = {}
    for case in cases:
        weight = case.similarity if case.similarity is not None else 1.0
        for label in case.labels:
            key = (label.taxonomy_id, label.topic_id) if label.topic_id else (None, label.name.lower())
            hint = hints.setdefault(
                key,
                TopicHint(
                    taxonomy_id=label.taxonomy_id, topic_id=label.topic_id, name=label.name, source=label.source,
                    cases=0, weight=0.0, affair_ids=[],
                ),
            )
            hint.cases += 1
            hint.weight = round(hint.weight + weight, 3)
            hint.affair_ids.append(case.affair.id)
    return sorted(hints.values(), key=lambda h: (h.weight, h.cases), reverse=True)


class SimilarCasesService:
    def __init__(
        self,
        writer: KeywordWriter,
        engine: AffairSearchEngine,
        ranker: SimilarityRanker | None = None,
        labels: LabelLookup | None = None,
        *,
        max_concurrency: int = 8,
    ) -> None:
        self._writer = writer
        self._engine = engine
        self._ranker = ranker
        self._labels = labels
        self._limit = asyncio.Semaphore(max_concurrency)  # shared by all requests: be gentle with OpenParlData

    # ---------- words ----------

    async def _keywords(self, document: SourceDocument, options: SimilarOptions, warnings: list[str]) -> DocumentKeywords:
        try:
            keywords = await self._writer.keywords(document, options.languages)
        except Exception as error:  # the search still works with the title's words
            log.warning("Keyword writing failed: %s", error)
            warnings.append(f"Apertus could not read the document ({type(error).__name__}); searched words of its title.")
            keywords = DocumentKeywords()
        words: dict[str, list[str]] = {}
        for lang in options.languages:
            kept: list[str] = []
            for word in keywords.words.get(lang, []):
                if lang == "de":
                    word = word.replace("ß", "ss")  # Swiss spelling: titles never use ß
                if word.lower() not in PROCEDURAL and word.lower() not in {k.lower() for k in kept}:
                    kept.append(word)
            words[lang] = kept[:WORDS_PER_LANGUAGE]
        if not any(words.values()) and options.languages:
            title = document.sections.get("title") or document.title or ""
            text = " ".join(t for name, t in document.sections.items() if name != "title") or title
            language = document.language if document.language in options.languages else guess_language(text, options.languages)
            words[language] = title_words(title)
            if not warnings:
                warnings.append("Apertus wrote no title words; searched words of the document's title.")
        return DocumentKeywords(subject=keywords.subject, words=words)

    # ---------- search ----------

    async def _search(
        self, query: str, language: str, limit: int, options: SimilarOptions, warnings: list[str]
    ) -> list[AffairSummary]:
        async with self._limit:
            try:
                return await self._engine.search_affairs(
                    query, language=language, scope="metadata", mode="natural", limit=limit, body_keys=options.body_keys
                )
            except Exception as error:
                warnings.append(f"Search for {query!r} ({language}) failed: {error}")
                return []

    async def _language_queries(
        self, language: str, words: list[str], options: SimilarOptions, warnings: list[str]
    ) -> list[tuple[SimilarQuery, list[AffairSummary]]]:
        """Specific words alone, core words alone (newest hits), broad words in pairs."""
        probes = await asyncio.gather(*(self._search(w, language, SINGLE_MAX + 1, options, warnings) for w in words))
        alive = [(rank, word, hits) for rank, (word, hits) in enumerate(zip(words, probes)) if hits]
        runs: list[tuple[SimilarQuery, list[AffairSummary]]] = []
        specific: set[str] = set()
        for rank, word, hits in alive:
            if len(hits) <= SINGLE_MAX:
                runs.append((SimilarQuery(language=language, query=word, hits=len(hits)), hits))
                specific.add(word)
            elif rank < CORE_WORDS:
                runs.append((SimilarQuery(language=language, query=word, hits=len(hits)), hits[:CORE_LIMIT]))
        head = [word for _, word, _ in alive[:PAIR_WORDS]]
        pairs = [f"{a} {b}" for i, a in enumerate(head) for b in head[i + 1 :] if a not in specific or b not in specific]
        results = await asyncio.gather(*(self._search(p, language, PAIR_LIMIT, options, warnings) for p in pairs[:MAX_PAIRS]))
        runs += [
            (SimilarQuery(language=language, query=p, hits=len(hits)), hits)
            for p, hits in zip(pairs, results)
            if hits
        ]
        return runs

    # ---------- the use case ----------

    async def find(self, document: SourceDocument, options: SimilarOptions | None = None) -> SimilarOutcome:
        options = options or SimilarOptions()
        if not any(text.strip() for text in document.sections.values()):
            raise ValueError("The document has no text to compare.")
        warnings: list[str] = []
        keywords = await self._keywords(document, options, warnings)
        per_language = await asyncio.gather(
            *(self._language_queries(lang, words, options, warnings) for lang, words in keywords.words.items() if words)
        )
        runs = [run for part in per_language for run in part]

        source = document.affair
        groups: dict[tuple[str, str], _Group] = {}
        seen: set[int] = set()
        for query, hits in runs:
            weight = 1 / math.log2(2 + query.hits)  # a hit of a specific word says more than one of a broad word
            touched: set[tuple[str, str]] = set()
            for affair in hits:
                if source and (
                    affair.id == source.id
                    or (affair.number and (affair.body_key, affair.number) == (source.body_key, source.number))
                ):
                    continue
                key = _group_key(affair)
                group = groups.setdefault(key, _Group())
                if affair.id not in seen:
                    seen.add(affair.id)
                    group.members.append(affair)
                if key not in touched:  # each query counts once per group
                    touched.add(key)
                    group.matched_by.append(QueryMatch(language=query.language, query=query.query))
                    group.specificity += weight

        candidates = sorted(groups.values(), key=lambda g: (g.specificity, g.representative.begin_date or date.min), reverse=True)
        ranked = False
        if options.rank and candidates:
            if self._ranker is None:
                warnings.append("Ranking needs a TypeSafe key; cases are ordered by how specific their matching words are.")
            else:
                to_rank = candidates[:MAX_RANKED]
                try:
                    scores = await self._ranker.score(document, [g.representative for g in to_rank])
                    for group, score in zip(to_rank, scores):
                        group.similarity = score
                    candidates = sorted(to_rank, key=lambda g: (g.similarity or 0.0, g.specificity), reverse=True)
                    candidates = [g for g in candidates if (g.similarity or 0.0) >= options.min_similarity]
                    ranked = True
                except Exception as error:
                    log.warning("Similarity ranking failed: %s", error)
                    warnings.append(f"Ranking failed ({type(error).__name__}); cases are ordered by how specific their matching words are.")
        selected = candidates[: options.max_results]

        known = self._labels.labels([m.id for g in selected for m in g.members]) if self._labels else {}
        cases = []
        for group in selected:
            labels: list[KnownLabel] = []
            for member in sorted(group.members, key=lambda a: a.begin_date or date.min, reverse=True):
                for label in known.get(member.id, []):
                    if label not in labels:
                        labels.append(label)
            representative = group.representative
            cases.append(
                SimilarCase(
                    affair=representative,
                    similarity=group.similarity,
                    matched_by=group.matched_by,
                    labels=labels,
                    same_title=[m for m in group.members if m.id != representative.id],
                )
            )
        return SimilarOutcome(
            document=DocumentInfo(
                kind=document.kind.value,
                reference=document.reference,
                title=document.title,
                body_key=document.body_key,
                language=document.language,
                affair=document.affair,
                sections={name: len(text) for name, text in document.sections.items()},
            ),
            subject=keywords.subject,
            keywords=keywords.words,
            queries=[query for query, _ in runs],
            cases=cases,
            topics=topic_hints(cases),
            candidates=len(groups),
            ranked=ranked,
            warnings=warnings,
        )
