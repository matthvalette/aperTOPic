from parltopics.domain.models import TextBlock
from parltopics.services.documents import sections_from_texts

BLOCKS = [
    TextBlock(kind="title", language="de", text="Titel"),
    TextBlock(kind="title", language="fr", text="Titre"),
    TextBlock(kind="title", language="it", text="Titolo"),
    TextBlock(kind="submitted_text", language="de", text="Der Bundesrat wird beauftragt"),
    TextBlock(kind="submitted_text", language="fr", text="Le Conseil fédéral est chargé, plus long"),
    TextBlock(kind="submitted_text", language="it", text="Il Consiglio federale è incaricato, molto più lungo"),
    TextBlock(kind="answer", language="de", text="Antwort"),
]


def test_requested_language_wins():
    sections, chosen = sections_from_texts(BLOCKS, "fr")
    assert chosen == "fr"
    assert sections == {"title": "Titre", "submitted_text": "Le Conseil fédéral est chargé, plus long"}


def test_ties_prefer_german_and_answer_is_excluded():
    sections, chosen = sections_from_texts(BLOCKS, None)
    assert chosen == "de"
    assert "answer" not in sections


def test_answer_can_be_included():
    sections, _ = sections_from_texts(BLOCKS, "de", ("title", "submitted_text", "answer"))
    assert sections["answer"] == "Antwort"
