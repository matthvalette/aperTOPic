"""Request bodies of the HTTP API. Responses reuse the service and domain models."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from ..services.classify import DEFAULT_TAXONOMIES, CustomTopic, EditedTopic
from ..services.search import SearchOptions
from ..services.similar import SimilarOptions


class SearchRequest(SearchOptions):
    query: str = Field(min_length=2, max_length=500, examples=["artificial intelligence in public administration"])


class ClassifyRequest(BaseModel):
    reference: str | None = Field(
        default=None,
        description="An OpenParlData link or id, a files.openparldata.ch document link, or a Curia Vista link.",
        examples=["https://openparldata.ch/item/affairs/70435"],
    )
    text: str | None = Field(default=None, max_length=200_000, description="Text to classify instead of a reference.")
    title: str | None = Field(default=None, max_length=500)
    taxonomies: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TAXONOMIES),
        description="Label sets to score. See GET /taxonomies.",
    )
    custom_topics: list[CustomTopic] = Field(default_factory=list, max_length=50, description="Ad-hoc topics")
    aps_topics: list[EditedTopic] | None = Field(
        default=None,
        max_length=300,
        description="An edited copy of the APS topics (rename, re-describe, delete or add, each with its chapter). "
        "Replaces the 165 APS topics for this request; chapter scores follow the edited chapters.",
    )
    language: str | None = Field(
        default=None, description="Preferred text language for multilingual affairs (de, fr, it)."
    )
    include_answer: bool = Field(default=False, description="Also use the Federal Council's answer.")
    threshold: float | None = Field(
        default=None, ge=0, le=1, description="Overrides each label set's tuned default threshold."
    )

    @model_validator(mode="after")
    def one_input(self) -> "ClassifyRequest":
        if bool(self.reference) == bool(self.text):
            raise ValueError("Send either `reference` or `text`.")
        return self


class SimilarRequest(SimilarOptions):
    reference: str | None = Field(
        default=None,
        description="An OpenParlData link or id, a files.openparldata.ch document link, or a Curia Vista link.",
        examples=["https://openparldata.ch/item/affairs/70435"],
    )
    text: str | None = Field(default=None, max_length=200_000, description="Text to compare instead of a reference.")
    title: str | None = Field(default=None, max_length=500)
    language: str | None = Field(
        default=None, description="Preferred text language for multilingual affairs (de, fr, it)."
    )
    include_answer: bool = Field(default=False, description="Also read the Federal Council's answer.")

    @model_validator(mode="after")
    def one_input(self) -> "SimilarRequest":
        if bool(self.reference) == bool(self.text):
            raise ValueError("Send either `reference` or `text`.")
        return self
