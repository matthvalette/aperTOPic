from parltopics.adapters.taxonomies import APS, CURIA
from parltopics.domain.models import Taxonomy, TaxonomyKind, Topic
from parltopics.services.classify import ClassificationService, EditedTopic


def _taxonomy(taxonomy_id: str) -> Taxonomy:
    return Taxonomy(
        id=taxonomy_id,
        name=taxonomy_id,
        kind=TaxonomyKind.MULTI_LABEL,
        description="base",
        source="test",
        default_threshold=0.75,
        topics=[Topic(id="1.1.1", name="Nationale Identität", group="Politische Grundfragen")],
    )


class _Provider:
    def get(self, taxonomy_id: str) -> Taxonomy:
        return _taxonomy(taxonomy_id)

    def list(self) -> list[Taxonomy]:
        return [_taxonomy(APS), _taxonomy(CURIA)]


def test_edited_aps_topics_replace_the_original_list():
    service = ClassificationService(classifier=None, taxonomies=_Provider())
    chosen = service.resolve_taxonomies(
        [APS, CURIA],
        aps_topics=[
            EditedTopic(id="1.1.1", name="Identität", group="Politische Grundfragen"),
            EditedTopic(name="Digitalisierung", description="E-Government", group="Medien"),
            EditedTopic(name="Digitalisierung", group="Medien"),
        ],
    )
    assert [t.id for t in chosen] == [CURIA, APS]
    aps = chosen[1]
    assert aps.default_threshold == 0.75
    assert [(t.id, t.name, t.group) for t in aps.topics] == [
        ("1.1.1", "Identität", "Politische Grundfragen"),
        ("digitalisierung", "Digitalisierung", "Medien"),
        ("digitalisierung-x", "Digitalisierung", "Medien"),
    ]


def test_without_edits_the_stored_aps_list_is_used():
    service = ClassificationService(classifier=None, taxonomies=_Provider())
    (aps,) = service.resolve_taxonomies([APS])
    assert aps.topics[0].name == "Nationale Identität"
