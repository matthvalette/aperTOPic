from datetime import date, timedelta

import pytest

from parltopics.domain.models import AffairSummary, DocumentKeywords, KnownLabel, SourceDocument, SourceKind
from parltopics.services.similar import SimilarCasesService, SimilarOptions, title_words, topic_hints

BASE = date(2026, 1, 1)


def affair(i, title=None, body="CHE", days_ago=0, number=None):
    return AffairSummary(
        id=i, body_key=body, number=number, title={"de": title or f"Affair {i}"},
        begin_date=BASE - timedelta(days=days_ago), url=f"https://openparldata.ch/item/affairs/{i}", url_api="",
    )


def document(source=None, title="Wolf und Herdenschutz", language="de"):
    return SourceDocument(
        kind=SourceKind.AFFAIR if source else SourceKind.TEXT, title=title, language=language, affair=source,
        sections={"title": title, "submitted_text": "Der Regierungsrat wird gefragt, wie er den Herdenschutz stärkt."},
    )


class FakeWriter:
    def __init__(self, words=None, fail=False):
        self.words, self.fail = words or {}, fail

    async def keywords(self, document, languages):
        if self.fail:
            raise RuntimeError("gateway down")
        return DocumentKeywords(subject="Wolves and herd protection.", words=self.words)


class FakeEngine:
    def __init__(self, results):
        self.results, self.calls = results, []

    async def search_affairs(self, query, *, language, scope, mode, limit, body_keys=()):
        self.calls.append((language, query, limit))
        return self.results.get((language, query), [])[:limit]


class FakeRanker:
    def __init__(self, scores=None, fail=False):
        self.scores, self.fail = scores or {}, fail

    async def score(self, document, affairs):
        if self.fail:
            raise RuntimeError("jev down")
        return [self.scores.get(a.id, 0.0) for a in affairs]


class FakeLabels:
    def __init__(self, labels):
        self._labels = labels

    def labels(self, affair_ids):
        return {i: self._labels[i] for i in affair_ids if i in self._labels}


def broad(start, n):
    return [affair(start + k, days_ago=k) for k in range(n)]  # newest first, as OpenParlData returns them


@pytest.mark.anyio
async def test_specific_words_alone_core_words_capped_broad_words_paired():
    engine = FakeEngine({
        ("de", "Herdenschutz"): [affair(1), affair(2)],
        ("de", "Wolf"): broad(100, 70),  # broad, but it names the subject
        ("de", "Schafe"): broad(300, 70),  # broad and not a core word
        ("de", "Herdenschutz Wolf"): [affair(3)],
        ("de", "Herdenschutz Schafe"): [affair(4)],
        ("de", "Wolf Schafe"): [affair(5)],
    })
    words = {"de": ["Herdenschutz", "Wolf", "Kanton", "Schafe", "Alpen"]}
    service = SimilarCasesService(FakeWriter(words), engine)
    outcome = await service.find(document(), SimilarOptions(languages=["de"], rank=False, max_results=50))

    run = {q.query: q.hits for q in outcome.queries}
    assert run == {"Herdenschutz": 2, "Wolf": 61, "Herdenschutz Wolf": 1, "Herdenschutz Schafe": 1, "Wolf Schafe": 1}
    assert ("de", "Kanton", 61) not in engine.calls  # procedural words are never searched
    assert outcome.keywords["de"] == ["Herdenschutz", "Wolf", "Schafe", "Alpen"]
    ids = {c.affair.id for c in outcome.cases}
    assert {1, 2, 3, 4, 5} <= ids
    assert ids & set(range(100, 130)) and not ids & set(range(130, 170))  # only Wolf's newest 30 hits
    assert not ids & set(range(300, 370))  # a broad word that is not core is never used alone
    assert {limit for _, q, limit in engine.calls if " " in q} == {30}


@pytest.mark.anyio
async def test_source_affair_and_its_other_record_are_left_out():
    source = affair(1, number="24.3010")
    engine = FakeEngine({("de", "Herdenschutz"): [affair(1, number="24.3010"), affair(2, number="24.3010"), affair(3)]})
    service = SimilarCasesService(FakeWriter({"de": ["Herdenschutz"]}), engine)
    outcome = await service.find(document(source), SimilarOptions(languages=["de"], rank=False))
    assert [c.affair.id for c in outcome.cases] == [3]


@pytest.mark.anyio
async def test_same_titles_are_one_case_with_the_labels_of_all():
    older = affair(7, title="Wolf: Herdenschutz stärken", days_ago=900)
    newer = affair(8, title="Wolf:  herdenschutz stärken", days_ago=10)  # same title, spacing and case aside
    labels = FakeLabels({7: [KnownLabel(taxonomy_id="curia_subject_areas", topic_id="16", name="Umwelt", source="Curia")]})
    engine = FakeEngine({("de", "Herdenschutz"): [newer, older]})
    service = SimilarCasesService(FakeWriter({"de": ["Herdenschutz"]}), engine, labels=labels)
    outcome = await service.find(document(), SimilarOptions(languages=["de"], rank=False))
    assert len(outcome.cases) == 1 and outcome.candidates == 1
    case = outcome.cases[0]
    assert case.affair.id == 8 and [a.id for a in case.same_title] == [7]
    assert [l.name for l in case.labels] == ["Umwelt"]


@pytest.mark.anyio
async def test_ranking_orders_filters_and_cuts():
    engine = FakeEngine({("de", "Herdenschutz"): [affair(3), affair(4), affair(5)]})
    ranker = FakeRanker({3: 0.9, 4: 0.2, 5: 0.6})
    service = SimilarCasesService(FakeWriter({"de": ["Herdenschutz"]}), engine, ranker)
    outcome = await service.find(document(), SimilarOptions(languages=["de"]))
    assert outcome.ranked and [c.affair.id for c in outcome.cases] == [3, 5]  # 4 is below min_similarity
    top = await service.find(document(), SimilarOptions(languages=["de"], max_results=1))
    assert [c.affair.id for c in top.cases] == [3]


@pytest.mark.anyio
async def test_ranking_failure_falls_back_to_specific_matches_first():
    engine = FakeEngine({("de", "Wolf"): broad(100, 70), ("de", "Herdenschutzhunde"): [affair(9, days_ago=4000)]})
    service = SimilarCasesService(FakeWriter({"de": ["Wolf", "Herdenschutzhunde"]}), engine, FakeRanker(fail=True))
    outcome = await service.find(document(), SimilarOptions(languages=["de"], max_results=3))
    assert not outcome.ranked and any("Ranking failed" in w for w in outcome.warnings)
    assert outcome.cases[0].affair.id == 9  # matched by a word with one hit, though it is the oldest


@pytest.mark.anyio
async def test_without_apertus_the_title_words_are_searched():
    engine = FakeEngine({("de", "Herdenschutz"): [affair(3)]})
    service = SimilarCasesService(FakeWriter(fail=True), engine)
    outcome = await service.find(document(title="Wolf und Herdenschutz"), SimilarOptions(rank=False))
    assert [c.affair.id for c in outcome.cases] == [3]
    assert outcome.keywords["de"] == ["Herdenschutz"]
    assert any("Apertus could not read the document" in w for w in outcome.warnings)


@pytest.mark.anyio
async def test_empty_document_is_rejected():
    service = SimilarCasesService(FakeWriter(), FakeEngine({}))
    with pytest.raises(ValueError):
        await service.find(SourceDocument(kind=SourceKind.TEXT, sections={"document": "  "}))


def test_topic_hints_weigh_labels_by_similarity():
    from parltopics.services.similar import SimilarCase

    umwelt = KnownLabel(taxonomy_id="curia_subject_areas", topic_id="16", name="Umwelt", source="Curia")
    landwirtschaft = KnownLabel(taxonomy_id="curia_subject_areas", topic_id="24", name="Landwirtschaft", source="Curia")
    cases = [
        SimilarCase(affair=affair(1), similarity=0.9, labels=[umwelt, landwirtschaft]),
        SimilarCase(affair=affair(2), similarity=0.5, labels=[umwelt]),
    ]
    hints = topic_hints(cases)
    assert [(h.name, h.cases, h.weight) for h in hints] == [("Umwelt", 2, 1.4), ("Landwirtschaft", 1, 0.9)]
    assert hints[0].affair_ids == [1, 2]


def test_title_words_skip_short_and_procedural_words():
    assert title_words("Motion: Wolf und Herdenschutz im Kanton") == ["Herdenschutz"]


@pytest.mark.anyio
async def test_german_words_use_swiss_spelling():
    engine = FakeEngine({("de", "grosse Raubtiere"): [affair(3)]})
    words = {"de": ["große Raubtiere", "grosse Raubtiere"], "fr": ["grands prédateurs"]}
    service = SimilarCasesService(FakeWriter(words), engine)
    outcome = await service.find(document(), SimilarOptions(languages=["de", "fr"], rank=False))
    assert outcome.keywords == {"de": ["grosse Raubtiere"], "fr": ["grands prédateurs"]}
    assert [c.affair.id for c in outcome.cases] == [3]
