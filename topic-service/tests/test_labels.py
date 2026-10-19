import json

from parltopics.adapters.labels import LabelledDataLabels
from parltopics.domain.models import Taxonomy, TaxonomyKind, Topic


class FakeTaxonomies:
    def list(self):
        return [
            Taxonomy(id="curia_subject_areas", name="c", kind=TaxonomyKind.MULTI_LABEL, description="", source="t",
                     topics=[Topic(id="48", name="Verkehr")]),
            Taxonomy(id="tg_subject_codes", name="t", kind=TaxonomyKind.SINGLE_LABEL, description="", source="t",
                     topics=[Topic(id="81.4", name="81.4 Umweltschutz")]),
            Taxonomy(id="sg_law_collection", name="s", kind=TaxonomyKind.SINGLE_LABEL, description="", source="t",
                     topics=[Topic(id="arbeit-und-gewerbe", name="Arbeit und Gewerbe")]),
            Taxonomy(id="digitalisation", name="d", kind=TaxonomyKind.BINARY, description="", source="t",
                     topics=[Topic(id="digitalisation", name="Digitalisierung")]),
        ]

    def get(self, taxonomy_id):
        return next(t for t in self.list() if t.id == taxonomy_id)


def write_data(tmp_path):
    federal = [
        {"openparldata_id": 1, "topic_ids": [48, 999], "topics_de": ["Verkehr", "Unbekannt"]},
        {"openparldata_id": 2, "topic_ids": [], "topics_de": []},
    ]
    cantonal = [
        {"openparldata_id": 10, "body_key": "TG", "keywords": ["Umweltschutz"], "keyword_codes": ["81.4"]},
        {"openparldata_id": 11, "body_key": "SG", "keywords": ["Arbeit und Gewerbe"], "keyword_codes": []},
        {"openparldata_id": 12, "body_key": "1711", "keywords": ["Tiefbau"], "keyword_codes": []},
    ]
    (tmp_path / "che_affairs_keywords.jsonl").write_text("\n".join(json.dumps(r) for r in federal), encoding="utf-8")
    (tmp_path / "cantonal_affairs_keywords.jsonl").write_text("\n".join(json.dumps(r) for r in cantonal), encoding="utf-8")
    (tmp_path / "politmonitor_digitalisierung.csv").write_text("openparldata_id,body_key\n1,CHE\n", encoding="utf-8")


def test_labels_link_to_label_sets_where_they_can(tmp_path):
    write_data(tmp_path)
    labels = LabelledDataLabels(tmp_path, FakeTaxonomies())
    found = labels.labels([1, 2, 10, 11, 12, 99])
    assert [(l.taxonomy_id, l.topic_id, l.name) for l in found[1]] == [
        ("curia_subject_areas", "48", "Verkehr"),
        (None, None, "Unbekannt"),  # not a topic of the label set: shown as text
        ("digitalisation", "digitalisation", "Digitalisierung"),
    ]
    assert (found[10][0].taxonomy_id, found[10][0].topic_id, found[10][0].name) == ("tg_subject_codes", "81.4", "81.4 Umweltschutz")
    assert found[11][0].topic_id == "arbeit-und-gewerbe"
    assert found[12][0].taxonomy_id is None and found[12][0].name == "Tiefbau"
    assert 2 not in found and 99 not in found


def test_missing_files_mean_no_labels(tmp_path):
    assert LabelledDataLabels(tmp_path).labels([1]) == {}
