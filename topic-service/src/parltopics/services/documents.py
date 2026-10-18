"""Turns a link, an id, an uploaded file or pasted text into a `SourceDocument`."""

from __future__ import annotations

from ..domain.models import (
    LANGUAGE_PREFERENCE,
    AffairSummary,
    SourceDocument,
    SourceKind,
    TextBlock,
    pick_language,
)
from ..domain.ports import AffairRepository, TextExtractor
from .references import Reference, ReferenceKind, parse_reference

# Federal texts used for classification. The Federal Council's answer is left out by default:
# subject areas are assigned when an affair is submitted, before any answer exists.
DEFAULT_SECTIONS = ("title", "lead", "submitted_text", "reasoning")
MAX_DOCS = 3


def sections_from_texts(
    blocks: list[TextBlock], language: str | None, include: tuple[str, ...] = DEFAULT_SECTIONS
) -> tuple[dict[str, str], str | None]:
    """Pick one language for all sections: the requested one if present, else the most complete."""
    by_language: dict[str, dict[str, str]] = {}
    for block in blocks:
        if block.kind in include:
            by_language.setdefault(block.language, {})[block.kind] = block.text
    if not by_language:
        return {}, None
    if language and language in by_language:
        chosen = language
    else:
        # Most sections first; on a tie, German, then French, Italian, Romansh.
        order = {lang: i for i, lang in enumerate(LANGUAGE_PREFERENCE)}
        chosen = max(by_language, key=lambda lang: (len(by_language[lang]), -order.get(lang, 99)))
    return by_language[chosen], chosen


class DocumentResolver:
    def __init__(self, repository: AffairRepository, extractor: TextExtractor) -> None:
        self._repo = repository
        self._extractor = extractor

    async def from_reference(
        self, value: str, *, language: str | None = None, include_answer: bool = False
    ) -> SourceDocument:
        ref = parse_reference(value)
        if ref.kind is ReferenceKind.CURIA_VISTA:
            affair = await self._repo.find_affair(body_key="CHE", external_id=ref.value)
            if affair is None:
                raise LookupError(f"No federal affair with Curia Vista id {ref.value} in OpenParlData")
            return await self.from_affair(affair, language=language, include_answer=include_answer)
        if ref.kind is ReferenceKind.AFFAIR:
            affair = await self._repo.get_affair(int(ref.value))
            return await self.from_affair(affair, language=language, include_answer=include_answer)
        if ref.kind is ReferenceKind.DOC:
            return await self._from_doc(int(ref.value))
        return await self._from_file(ref)

    async def from_affair(
        self, affair: AffairSummary, *, language: str | None = None, include_answer: bool = False
    ) -> SourceDocument:
        include = DEFAULT_SECTIONS + (("answer",) if include_answer else ())
        sections, chosen = sections_from_texts(await self._repo.get_texts(affair.id), language, include)
        if not sections.get("submitted_text") and not sections.get("reasoning"):
            # Cantonal and municipal affairs rarely have texts; their content is in documents.
            docs = [d for d in await self._repo.get_docs(affair.id, limit=MAX_DOCS) if d.text]
            for index, doc in enumerate(docs, start=1):
                sections[f"document_{index}"] = (f"{doc.name}\n\n" if doc.name else "") + doc.text
        prefer = (language,) if language else ()
        title = pick_language(affair.title, prefer + ("de", "fr", "it", "rm"))
        if title:
            sections.setdefault("title", title)
        return SourceDocument(
            kind=SourceKind.AFFAIR,
            reference=str(affair.id),
            title=title,
            body_key=affair.body_key,
            affair_type=affair.type.get("en") or affair.type.get("de"),
            language=chosen or language,
            affair=affair,
            sections=sections,
        )

    async def _from_doc(self, doc_id: int) -> SourceDocument:
        doc = await self._repo.get_doc(doc_id)
        affair = await self._repo.get_affair(doc.affair_id) if doc.affair_id else None
        sections = {"document": doc.text}
        title = doc.name or (affair.best_title() if affair else None)
        if title:
            sections["title"] = title
        return SourceDocument(
            kind=SourceKind.DOC,
            reference=str(doc_id),
            title=title,
            body_key=affair.body_key if affair else None,
            affair_type=(affair.type.get("en") if affair else None),
            affair=affair,
            sections=sections,
        )

    async def _from_file(self, ref: Reference) -> SourceDocument:
        data, content_type = await self._repo.download_file(ref.value, max_bytes=25_000_000)
        text = self._extractor.extract(data, filename=ref.value, content_type=content_type)
        return SourceDocument(kind=SourceKind.FILE, reference=ref.value, sections={"document": text})

    def from_upload(self, data: bytes, *, filename: str | None, content_type: str | None, title: str | None = None) -> SourceDocument:
        text = self._extractor.extract(data, filename=filename, content_type=content_type)
        sections = {"document": text}
        if title:
            sections["title"] = title
        return SourceDocument(kind=SourceKind.UPLOAD, reference=filename, title=title or filename, sections=sections)

    @staticmethod
    def from_text(text: str, *, title: str | None = None, body_key: str | None = None) -> SourceDocument:
        sections = {"document": text.strip()}
        if title:
            sections["title"] = title
        return SourceDocument(kind=SourceKind.TEXT, title=title, body_key=body_key, sections=sections)
