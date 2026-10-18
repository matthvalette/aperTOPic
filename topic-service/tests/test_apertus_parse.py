from parltopics.adapters.apertus import parse_variants


def test_parses_fenced_json_and_keeps_apostrophes():
    content = '```json\n{"de": ["KI Verwaltung", "ki verwaltung", "\\"Algorithmen\\""], "fr": ["IA dans l\'administration"]}\n```'
    result = {v.language: v.queries for v in parse_variants(content, ["de", "fr", "it"], 3, fallback="AI")}
    assert result["de"] == ["KI Verwaltung", "Algorithmen"]  # duplicate removed, quotes stripped
    assert result["fr"] == ["IA dans l'administration"]
    assert result["it"] == ["AI"]  # missing language falls back to the request


def test_invalid_json_falls_back():
    result = parse_variants("sorry, no JSON", ["de"], 3, fallback="Lärm")
    assert result[0].queries == ["Lärm"]


def test_caps_number_of_variants():
    result = parse_variants('{"de": ["a", "b", "c", "d"]}', ["de"], 2, fallback="x")
    assert result[0].queries == ["a", "b"]
