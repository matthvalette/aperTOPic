from datetime import date

import pytest

from parltopics.domain.models import AffairSummary, QueryVariants
from parltopics.services.search import SearchOptions, SearchService


def affair(i, day):
    return AffairSummary(id=i, body_key="CHE", title={"de": f"Affair {i}"}, begin_date=date(2026, 1, day),
                         url=f"https://openparldata.ch/item/affairs/{i}", url_api="")


class FakeTranslator:
    async def translate(self, request, languages, variants_per_language):
        return [QueryVariants(language=lang, queries=[f"{request}-{lang}"]) for lang in languages]


class FakeEngine:
    async def search_affairs(self, query, *, language, scope, mode, limit, body_keys=()):
        if language == "rm":
            raise RuntimeError("boom")
        return {"de": [affair(1, 1), affair(2, 2)], "fr": [affair(2, 2)], "it": [affair(3, 3)]}[language]


class FakeRanker:
    async def score(self, request, affairs):
        return [{1: 0.9, 2: 0.1, 3: 0.5}[a.id] for a in affairs]


@pytest.mark.anyio
async def test_merges_languages_and_reports_failures():
    service = SearchService(FakeTranslator(), FakeEngine())
    outcome = await service.search("noise", SearchOptions())
    assert [h.affair.id for h in outcome.hits] == [2, 3, 1]  # 2 matched twice, then newest
    assert {m.language for m in outcome.hits[0].matched_by} == {"de", "fr"}
    assert any("rm" in w for w in outcome.warnings)


@pytest.mark.anyio
async def test_ranking_orders_by_relevance():
    service = SearchService(FakeTranslator(), FakeEngine(), FakeRanker())
    outcome = await service.search("noise", SearchOptions(rank=True))
    assert outcome.ranked
    assert [h.affair.id for h in outcome.hits] == [1, 3, 2]
