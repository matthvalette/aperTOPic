"""Interfaces between modules.

Services depend only on these protocols. Adapters (OpenParlData, Apertus, Jev, file
extraction, labelled data) implement them, and `api/dependencies.py` wires one to the other.
Swap an adapter by writing another class with the same methods.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .models import (
    AffairSummary,
    Classification,
    DocumentText,
    QueryVariants,
    SourceDocument,
    Taxonomy,
    TextBlock,
)


class QueryTranslator(Protocol):
    """Turns a free-text request into search queries per language."""

    async def translate(
        self, request: str, languages: Sequence[str], variants_per_language: int
    ) -> list[QueryVariants]: ...


class AffairSearchEngine(Protocol):
    """Full-text search over affairs in one language."""

    async def search_affairs(
        self,
        query: str,
        *,
        language: str,
        scope: str,
        mode: str,
        limit: int,
        body_keys: Sequence[str] = (),
    ) -> list[AffairSummary]: ...


class AffairRepository(Protocol):
    """Read access to affairs, their texts and their documents."""

    async def get_affair(self, affair_id: int) -> AffairSummary: ...

    async def find_affair(
        self, *, body_key: str, external_id: str | None = None, number: str | None = None
    ) -> AffairSummary | None: ...

    async def get_texts(self, affair_id: int) -> list[TextBlock]: ...

    async def get_docs(self, affair_id: int, limit: int) -> list[DocumentText]: ...

    async def get_doc(self, doc_id: int) -> DocumentText: ...

    async def download_file(self, url: str, max_bytes: int) -> tuple[bytes, str | None]: ...


class TextExtractor(Protocol):
    """Extracts plain text from an uploaded or downloaded file."""

    def extract(self, data: bytes, *, filename: str | None, content_type: str | None) -> str: ...


class TopicClassifier(Protocol):
    """Scores one document against one or more taxonomies."""

    async def classify(
        self, document: SourceDocument, taxonomies: Sequence[Taxonomy], *, threshold: float | None = None
    ) -> list[Classification]:
        """`threshold` overrides each taxonomy's default threshold."""
        ...


class RelevanceRanker(Protocol):
    """Scores how relevant each affair is to a search request (0 to 1)."""

    async def score(self, request: str, affairs: Sequence[AffairSummary]) -> list[float]: ...


class TaxonomyProvider(Protocol):
    """The label sets known from the labelled data."""

    def list(self) -> list[Taxonomy]: ...

    def get(self, taxonomy_id: str) -> Taxonomy: ...
