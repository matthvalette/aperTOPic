from parltopics.adapters.apertus import document_prompt_text, parse_keywords
from parltopics.domain.models import SourceDocument, SourceKind


def test_parses_fenced_json_dedupes_and_strips_quotes():
    content = (
        '```json\n{"subject": " Wolves. ", "keywords": {"de": ["Wolf", "wolf", "«Herdenschutz»"], '
        '"fr": "loup", "it": [3, "lupo"]}}\n```'
    )
    result = parse_keywords(content, ["de", "fr", "it", "rm"])
    assert result.subject == "Wolves."
    assert result.words == {"de": ["Wolf", "Herdenschutz"], "fr": ["loup"], "it": ["lupo"], "rm": []}


def test_invalid_json_gives_no_words():
    result = parse_keywords("sorry, no JSON here", ["de"])
    assert result.subject is None and result.words == {"de": []}


def test_prompt_text_orders_sections_and_skips_repeated_attachments():
    pdf = "Der Regierungsrat wird beauftragt, " + "x " * 400
    document = SourceDocument(
        kind=SourceKind.AFFAIR, body_key="TG", affair_type="Motion",
        sections={"document_2": pdf, "title": "Herdenschutz", "document_1": pdf, "reasoning": "Weil Wölfe zunehmen."},
    )
    text = document_prompt_text(document, {"TG": {"name": "Thurgau"}})
    lines = text.splitlines()
    assert lines[:4] == ["Parliament: Thurgau (TG)", "Type: Motion", "Title: Herdenschutz", "Reasoning: Weil Wölfe zunehmen."]
    assert sum(line.startswith("Document:") for line in lines) == 1


def test_prompt_text_is_cut():
    document = SourceDocument(kind=SourceKind.TEXT, sections={"document": "Wort " * 5000})
    assert len(document_prompt_text(document, max_chars=1000, max_section=600)) <= 1000
