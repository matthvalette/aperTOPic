from typesafe_sdk import Choice, Noul

from parltopics.adapters.jev import build_questions, build_state
from parltopics.adapters.taxonomies import custom_taxonomy
from parltopics.domain.models import SourceDocument, SourceKind, Taxonomy, TaxonomyKind, Topic


def taxonomy(kind):
    return Taxonomy(
        id="t", name="t", kind=kind, description="", source="test",
        topics=[Topic(id="1", name="Verkehr", description="Rail and roads"), Topic(id="2", name="Energie")],
    )


def test_multi_label_is_one_noul_per_topic():
    questions, to_topic = build_questions(taxonomy(TaxonomyKind.MULTI_LABEL), "x0_")
    assert len(questions) == 2 and all(isinstance(q, Noul) for q in questions.values())
    assert sorted(to_topic.values()) == ["1", "2"]


def test_single_label_is_one_choice():
    questions, to_topic = build_questions(taxonomy(TaxonomyKind.SINGLE_LABEL), "x0_")
    assert list(questions) == ["x0_choice"] and isinstance(questions["x0_choice"], Choice)
    assert to_topic == {}


def test_custom_topics_get_unique_ids():
    t = custom_taxonomy([("Covid-19", None), ("covid 19", "duplicate name")])
    assert [x.id for x in t.topics] == ["covid-19", "covid-19-x"]


def test_state_orders_and_truncates_sections():
    document = SourceDocument(
        kind=SourceKind.TEXT,
        body_key="CHE",
        sections={"reasoning": "word " * 2000, "title": "Titel", "submitted_text": "Text"},
    )
    state = build_state(document, max_section_chars=100, max_state_chars=1000)
    assert list(state["affair"]) == ["parliament", "title", "submitted_text", "reasoning"]
    assert len(state["affair"]["reasoning"]) <= 104
