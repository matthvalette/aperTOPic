"""Multilingual search: one request, queries in every parliament language, merged results.

    request ──Apertus──▶ queries per language ──OpenParlData──▶ hits per query
            ──merge by affair──▶ (optional) Jev relevance ──▶ ranked results
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, Field

from ..domain.models import PARLIAMENT_LANGUAGES, QueryMatch, QueryVariants, SearchHit
from ..domain.ports import AffairSearchEngine, QueryTranslator, RelevanceRanker

log = logging.getLogger(__name__)


class SearchOptions(BaseModel):
    languages: list[str] = Field(default_factory=lambda: list(PARLIAMENT_LANGUAGES))
    variants_per_language: int = Field(default=3, ge=1, le=5)
    scope: str = Field(
        default="metadata",
        description="metadata (titles, fast), texts, docs, speeches, all, or a comma-separated mix. "
        "Full-text scopes take about 10 seconds per query.",
    )
    mode: str = Field(default="natural", description="natural, partial, exact or boolean")
    limit_per_query: int = Field(default=20, ge=1, le=100)
    body_keys: list[str] = Field(default_factory=list, description="Limit to parliaments, e.g. CHE, BE, 261")
    rank: bool = Field(default=False, description="Order results by Jev relevance to the request")
    max_results: int = Field(default=50, ge=1, le=300)


class SearchOutcome(BaseModel):
    request: str
    queries: list[QueryVariants]
    hits: list[SearchHit]
    unique_affairs: int
    ranked: bool
    warnings: list[str] = Field(default_factory=list)


class SearchService:
    def __init__(
        self,
        translator: QueryTranslator,
        engine: AffairSearchEngine,
        ranker: RelevanceRanker | None = None,
    ) -> None:
        self._translator = translator
        self._engine = engine
        self._ranker = ranker

    async def _queries(self, request: str, options: SearchOptions, warnings: list[str]) -> list[QueryVariants]:
        try:
            return await self._translator.translate(request, options.languages, options.variants_per_language)
        except Exception as error:  # the search still works untranslated
            log.warning("Query translation failed: %s", error)
            warnings.append(f"Translation failed ({type(error).__name__}); searched the request as written.")
            return [QueryVariants(language=lang, queries=[request]) for lang in options.languages]

    async def search(self, request: str, options: SearchOptions | None = None) -> SearchOutcome:
        options = options or SearchOptions()
        warnings: list[str] = []
        queries = await self._queries(request, options, warnings)

        jobs = [(variants.language, q) for variants in queries for q in variants.queries]
        results = await asyncio.gather(
            *(
                self._engine.search_affairs(
                    q,
                    language=lang,
                    scope=options.scope,
                    mode=options.mode,
                    limit=options.limit_per_query,
                    body_keys=options.body_keys,
                )
                for lang, q in jobs
            ),
            return_exceptions=True,
        )

        merged: dict[int, SearchHit] = {}
        for (lang, q), result in zip(jobs, results):
            if isinstance(result, BaseException):
                warnings.append(f"Search for {q!r} ({lang}) failed: {result}")
                continue
            for affair in result:
                hit = merged.setdefault(affair.id, SearchHit(affair=affair))
                hit.matched_by.append(QueryMatch(language=lang, query=q))

        hits = list(merged.values())
        ranked = False
        if options.rank and hits:
            if self._ranker is None:
                warnings.append("Ranking needs a TypeSafe key; results are ordered by matches and date.")
            else:
                try:
                    scores = await self._ranker.score(request, [h.affair for h in hits])
                    for hit, score in zip(hits, scores):
                        hit.relevance = score
                    ranked = True
                except Exception as error:
                    warnings.append(f"Ranking failed ({type(error).__name__}); ordered by matches and date.")

        hits.sort(key=lambda h: _sort_key(h, ranked), reverse=True)
        return SearchOutcome(
            request=request,
            queries=queries,
            hits=hits[: options.max_results],
            unique_affairs=len(merged),
            ranked=ranked,
            warnings=warnings,
        )


def _sort_key(hit: SearchHit, ranked: bool) -> tuple:
    newest = hit.affair.begin_date or date.min
    if ranked:
        return (hit.relevance or 0.0, len(hit.matched_by), newest)
    # Matched by more queries and languages first, then newest.
    return (len(hit.matched_by), newest)


def languages_found(hits: Sequence[SearchHit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        for lang in {m.language for m in hit.matched_by}:
            counts[lang] = counts.get(lang, 0) + 1
    return counts
