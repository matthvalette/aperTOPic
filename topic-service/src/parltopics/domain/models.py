"""Domain types shared by every module. Nothing in here does I/O."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["de", "fr", "it", "rm", "en"]
# Languages Swiss parliaments publish in. English is accepted as input only.
PARLIAMENT_LANGUAGES: tuple[Language, ...] = ("de", "fr", "it", "rm")
LANGUAGE_PREFERENCE: tuple[str, ...] = ("de", "fr", "it", "rm", "en")


def pick_language(values: dict[str, str], prefer: Sequence[str] = LANGUAGE_PREFERENCE) -> str | None:
    """Return the first non-empty value in order of preference, else any value."""
    for lang in prefer:
        if values.get(lang):
            return values[lang]
    return next((v for v in values.values() if v), None)


# ---------- affairs and documents ----------


class AffairSummary(BaseModel):
    """One parliamentary affair (motion, postulate, question, bill, ...)."""

    id: int
    body_key: str
    number: str | None = None
    title: dict[str, str] = Field(default_factory=dict)
    type: dict[str, str] = Field(default_factory=dict)
    begin_date: date | None = None
    url: str
    url_api: str
    url_external: dict[str, str] = Field(default_factory=dict)

    def best_title(self, prefer: Sequence[str] = LANGUAGE_PREFERENCE) -> str:
        return pick_language(self.title, prefer) or (self.number or str(self.id))


class TextBlock(BaseModel):
    """A short official text stored with an affair, in one language."""

    kind: str
    language: str
    text: str


class DocumentText(BaseModel):
    """An attached document (usually a PDF) and its extracted text."""

    id: int | None = None
    name: str | None = None
    url: str | None = None
    format: str | None = None
    affair_id: int | None = None
    text: str


class SourceKind(StrEnum):
    AFFAIR = "affair"
    DOC = "doc"
    FILE = "file"
    UPLOAD = "upload"
    TEXT = "text"


class SourceDocument(BaseModel):
    """Anything that can be classified, reduced to named text sections."""

    kind: SourceKind
    reference: str | None = None
    title: str | None = None
    body_key: str | None = None
    affair_type: str | None = None
    language: str | None = None
    affair: AffairSummary | None = None
    sections: dict[str, str] = Field(default_factory=dict)

    def total_chars(self) -> int:
        return sum(len(t) for t in self.sections.values())


# ---------- search ----------


class QueryVariants(BaseModel):
    """Search queries for one language, most direct first."""

    language: str
    queries: list[str]


class QueryMatch(BaseModel):
    language: str
    query: str


class SearchHit(BaseModel):
    affair: AffairSummary
    matched_by: list[QueryMatch] = Field(default_factory=list)
    relevance: float | None = Field(
        default=None, description="Jev probability that the affair is relevant, when ranking is on."
    )


# ---------- topics ----------


class TaxonomyKind(StrEnum):
    MULTI_LABEL = "multi_label"  # any number of topics may apply: one yes/no judgment per topic
    SINGLE_LABEL = "single_label"  # exactly one topic applies: one choice over all topics
    BINARY = "binary"  # one topic, present or not


class Topic(BaseModel):
    id: str
    name: str
    names: dict[str, str] = Field(default_factory=dict)
    code: str | None = None
    group: str | None = Field(default=None, description="Parent level, e.g. the APS chapter.")
    description: str | None = None
    group_names: dict[str, str] | None = Field(
        default=None, description="Parent (chapter) labels per language, e.g. {'de': ..., 'fr': ..., 'it': ...}."
    )
    domain_names: dict[str, str] | None = Field(
        default=None, description="Top-level domain labels per language."
    )


class Taxonomy(BaseModel):
    id: str
    name: str
    kind: TaxonomyKind
    description: str
    source: str
    topics: list[Topic]
    default_threshold: float = Field(
        default=0.5, description="Probability a topic needs to be assigned, unless the request sets one."
    )
    native_bodies: list[str] = Field(
        default_factory=list, description="Parliaments that use this scheme themselves."
    )

    def topic(self, topic_id: str) -> Topic:
        for t in self.topics:
            if t.id == topic_id:
                return t
        raise KeyError(topic_id)


class TopicScore(BaseModel):
    topic_id: str
    name: str
    probability: float


class Classification(BaseModel):
    taxonomy_id: str
    kind: TaxonomyKind
    scores: list[TopicScore] = Field(description="Every topic, highest probability first.")
    predicted: list[str] = Field(description="Topic ids the classifier assigns.")
    threshold: float | None = Field(
        default=None, description="Probability a topic needs to be assigned (multi-label, binary)."
    )
    confidence: float | None = Field(
        default=None, description="How concentrated a single-label choice is (0 to 1)."
    )
    groups: list[TopicScore] = Field(
        default_factory=list,
        description="Parent level (e.g. APS chapters): the highest probability among each group's topics.",
    )
    model: str


# ---------- similar cases ----------


class KnownLabel(BaseModel):
    """A label people gave an affair: a Curia Vista subject area, a cantonal subject, an editorial tag."""

    taxonomy_id: str | None = Field(
        default=None, description="The label set it belongs to, when the service has it (see GET /taxonomies)."
    )
    topic_id: str | None = None
    name: str
    source: str = Field(description="Who assigned it, e.g. the Parliamentary Services in Curia Vista.")


class DocumentKeywords(BaseModel):
    """Words that titles of affairs on the same subject as a document contain."""

    subject: str | None = Field(default=None, description="The document's subject in one sentence.")
    words: dict[str, list[str]] = Field(
        default_factory=dict, description="Per language, the title words, most distinctive first."
    )
