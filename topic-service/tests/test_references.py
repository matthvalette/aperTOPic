import pytest

from parltopics.services.references import ReferenceKind, parse_reference


@pytest.mark.parametrize(
    ("value", "kind", "ref"),
    [
        ("https://openparldata.ch/item/affairs/70435", ReferenceKind.AFFAIR, "70435"),
        ("https://api.openparldata.ch/v1/affairs/70435/texts", ReferenceKind.AFFAIR, "70435"),
        ("https://api.openparldata.ch/v1/docs/927844", ReferenceKind.DOC, "927844"),
        ("doc:927844", ReferenceKind.DOC, "927844"),
        ("  70435 ", ReferenceKind.AFFAIR, "70435"),
        (
            "https://www.parlament.ch/de/ratsbetrieb/suche-curia-vista/geschaeft?AffairId=20243010",
            ReferenceKind.CURIA_VISTA,
            "20243010",
        ),
        (
            "https://files.openparldata.ch/doc/SZ/553bfb4a922790e6f2cff073b194a666",
            ReferenceKind.FILE,
            "https://files.openparldata.ch/doc/SZ/553bfb4a922790e6f2cff073b194a666",
        ),
    ],
)
def test_parse_reference(value, kind, ref):
    parsed = parse_reference(value)
    assert parsed.kind is kind
    assert parsed.value == ref


def test_rejects_other_sites():
    with pytest.raises(ValueError):
        parse_reference("https://example.com/some.pdf")
