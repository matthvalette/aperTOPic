"""Topic classification: resolve the input, pick the label sets, ask the classifier."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from ..adapters.taxonomies import APS, CURIA, custom_taxonomy, slugify
from ..domain.models import AffairSummary, Classification, SourceDocument, Taxonomy, Topic
from ..domain.ports import TaxonomyProvider, TopicClassifier

DEFAULT_TAXONOMIES = (CURIA,)


class CustomTopic(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["Digitalisierung"])
    description: str | None = Field(
        default=None, max_length=1000, examples=["E-government, cybersecurity, AI and data protection"]
    )


class EditedTopic(BaseModel):
    """One topic of a label set the user edited: kept, renamed, re-described or newly added."""

    id: str | None = Field(default=None, max_length=64, description="The original topic id; empty for a new topic.")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    group: str | None = Field(default=None, max_length=200, description="Chapter the topic belongs to.")


def edited_taxonomy(base: Taxonomy, topics: Sequence[EditedTopic]) -> Taxonomy:
    """The base label set with its topic list replaced by the user's edited list."""
    seen: set[str] = set()
    built = []
    for t in topics:
        topic_id = t.id or slugify(t.name) or f"topic-{len(built) + 1}"
        while topic_id in seen:
            topic_id += "-x"
        seen.add(topic_id)
        built.append(Topic(id=topic_id, name=t.name, description=t.description, group=t.group))
    return base.model_copy(update={"topics": built, "description": f"{base.description} Edited in the request."})


class DocumentInfo(BaseModel):
    """What was classified, so a person can check it."""

    kind: str
    reference: str | None
    title: str | None
    body_key: str | None
    language: str | None
    affair: AffairSummary | None
    sections: dict[str, int] = Field(description="Section name and its length in characters")


class ClassificationOutcome(BaseModel):
    document: DocumentInfo
    classifications: list[Classification]


class ClassificationService:
    def __init__(self, classifier: TopicClassifier, taxonomies: TaxonomyProvider) -> None:
        self._classifier = classifier
        self._taxonomies = taxonomies

    def resolve_taxonomies(
        self,
        taxonomy_ids: Sequence[str],
        custom_topics: Sequence[CustomTopic] = (),
        aps_topics: Sequence[EditedTopic] | None = None,
    ) -> list[Taxonomy]:
        ids = [t for t in dict.fromkeys(taxonomy_ids) if not (aps_topics and t == APS)]
        chosen = [self._taxonomies.get(t) for t in ids]
        if aps_topics:
            chosen.append(edited_taxonomy(self._taxonomies.get(APS), aps_topics))
        if custom_topics:
            chosen.append(custom_taxonomy([(t.name, t.description) for t in custom_topics]))
        if not chosen:
            chosen = [self._taxonomies.get(t) for t in DEFAULT_TAXONOMIES]
        return chosen

    async def classify(
        self,
        document: SourceDocument,
        taxonomy_ids: Sequence[str] = DEFAULT_TAXONOMIES,
        custom_topics: Sequence[CustomTopic] = (),
        threshold: float | None = None,
        aps_topics: Sequence[EditedTopic] | None = None,
    ) -> ClassificationOutcome:
        if not any(text.strip() for text in document.sections.values()):
            raise ValueError("The document has no text to classify.")
        taxonomies = self.resolve_taxonomies(taxonomy_ids, custom_topics, aps_topics)
        results = await self._classifier.classify(document, taxonomies, threshold=threshold)
        return ClassificationOutcome(
            document=DocumentInfo(
                kind=document.kind.value,
                reference=document.reference,
                title=document.title,
                body_key=document.body_key,
                language=document.language,
                affair=document.affair,
                sections={name: len(text) for name, text in document.sections.items()},
            ),
            classifications=results,
        )
