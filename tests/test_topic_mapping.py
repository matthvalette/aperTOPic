"""Tests for topic_mapping pure functions (no Apertus calls)."""

from __future__ import annotations

import pytest

from topic_mapping.classify import MappingResult, validate_codes
from topic_mapping.coverage import compute_coverage, coverage_report
from topic_mapping.coverage_fill import merge_additions
from topic_mapping.data_loaders import SourceLabel
from topic_mapping.prompts import ApsTopic, build_mapping_prompt, format_aps_list


def _aps(code: str) -> ApsTopic:
    """Build a minimal ApsTopic for testing."""
    return ApsTopic(
        code=code,
        domain_de=f"Dom{code[0]}",
        domain_fr=f"DomFR{code[0]}",
        chapter_de=f"Kap{code[:3]}",
        chapter_fr=f"KapFR{code[:3]}",
        topic_de=f"Topic{code}",
        topic_fr=f"TopicFR{code}",
    )


def _source(label: str, scheme: str = "test", sid: str = "1") -> SourceLabel:
    return SourceLabel(
        scheme=scheme,
        source_id=sid,
        label_de=label,
        label_fr=None,
        label_it=None,
        affair_count=10,
        extra={},
    )


class TestValidateCodes:
    def test_valid_codes_pass(self) -> None:
        valid, invalid = validate_codes(["1.1.1", "8.5.6"], {"1.1.1", "8.5.6"})
        assert valid == ["1.1.1", "8.5.6"]
        assert invalid == []

    def test_invalid_codes_filtered(self) -> None:
        valid, invalid = validate_codes(["1.1.1", "9.9.9"], {"1.1.1"})
        assert valid == ["1.1.1"]
        assert invalid == ["9.9.9"]


class TestFormatApsList:
    def test_format_includes_code_and_names(self) -> None:
        out = format_aps_list([_aps("1.1.1")])
        assert "1.1.1" in out
        assert "Topic1.1.1" in out


class TestBuildMappingPrompt:
    def test_prompt_structure(self) -> None:
        topics = [_aps("1.1.1"), _aps("5.1.1")]
        msgs = build_mapping_prompt(
            source_scheme="test",
            source_label_de="Gesundheit",
            source_label_fr="Santé",
            source_label_it=None,
            affair_count=100,
            aps_topics=topics,
        )
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "Gesundheit" in msgs[1]["content"]
        assert "Santé" in msgs[1]["content"]
        assert "1.1.1" in msgs[1]["content"]
        assert "5.1.1" in msgs[1]["content"]

    def test_prompt_includes_few_shot_examples(self) -> None:
        topics = [_aps("1.1.1")]
        msgs = build_mapping_prompt(
            source_scheme="test",
            source_label_de="X",
            source_label_fr=None,
            source_label_it=None,
            affair_count=1,
            aps_topics=topics,
        )
        # Few-shot examples are embedded in the user message
        assert "BEISPIEL" in msgs[1]["content"]


class TestComputeCoverage:
    def test_full_coverage(self) -> None:
        topics = [_aps("1.1.1"), _aps("1.1.2")]
        r = MappingResult(
            source=_source("X"),
            primary_codes=["1.1.1"],
            secondary_codes=["1.1.2"],
        )
        cov = compute_coverage([r], topics)
        assert cov["coverage_pct"] == 100.0
        assert cov["uncovered_codes"] == []

    def test_partial_coverage(self) -> None:
        topics = [_aps("1.1.1"), _aps("1.1.2"), _aps("1.1.3")]
        r = MappingResult(source=_source("X"), primary_codes=["1.1.1"])
        cov = compute_coverage([r], topics)
        assert cov["coverage_pct"] == pytest.approx(33.33, abs=0.01)
        assert set(cov["uncovered_codes"]) == {"1.1.2", "1.1.3"}

    def test_per_code_attribution(self) -> None:
        topics = [_aps("1.1.1")]
        r1 = MappingResult(source=_source("A", scheme="s1", sid="1"), primary_codes=["1.1.1"])
        r2 = MappingResult(source=_source("B", scheme="s2", sid="2"), secondary_codes=["1.1.1"])
        cov = compute_coverage([r1, r2], topics)
        assert cov["per_code"]["1.1.1"]["primary"] == ["s1:1"]
        assert cov["per_code"]["1.1.1"]["secondary"] == ["s2:2"]


class TestCoverageReport:
    def test_report_mentions_pct(self) -> None:
        topics = [_aps("1.1.1")]
        cov = compute_coverage([], topics)
        report = coverage_report(cov, topics)
        assert "0.0%" in report
        assert "1.1.1" in report


class TestMergeAdditions:
    def test_merge_adds_edges(self) -> None:
        r = MappingResult(source=_source("A", scheme="s", sid="1"))
        additions = {"1.1.1": [("s:1", "primary")], "1.1.2": [("s:1", "secondary")]}
        n = merge_additions([r], additions)
        assert n == 2
        assert "1.1.1" in r.primary_codes
        assert "1.1.2" in r.secondary_codes

    def test_merge_skips_duplicates(self) -> None:
        r = MappingResult(source=_source("A", scheme="s", sid="1"), primary_codes=["1.1.1"])
        additions = {"1.1.1": [("s:1", "primary")]}
        n = merge_additions([r], additions)
        assert n == 0

    def test_merge_unknown_source_ignored(self) -> None:
        r = MappingResult(source=_source("A", scheme="s", sid="1"))
        additions = {"1.1.1": [("unknown:99", "primary")]}
        n = merge_additions([r], additions)
        assert n == 0
        assert r.primary_codes == []
