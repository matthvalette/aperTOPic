"""Core classification logic: map one source label to APS topics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from topic_mapping.apertus_client import ApertusClient, ApertusError
from topic_mapping.data_loaders import SourceLabel
from topic_mapping.prompts import ApsTopic, build_mapping_prompt

logger = logging.getLogger(__name__)


@dataclass
class MappingResult:
    """Outcome of mapping a single source label."""

    source: SourceLabel
    primary_codes: list[str] = field(default_factory=list)
    secondary_codes: list[str] = field(default_factory=list)
    method: str = "apertus"
    raw_response_hash: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to JSON-compatible dict."""
        return {
            "source_id": self.source.source_id,
            "source_label_de": self.source.label_de,
            "source_label_fr": self.source.label_fr,
            "source_label_it": self.source.label_it,
            "source_affair_count": self.source.affair_count,
            "aps_primary": self.primary_codes,
            "aps_secondary": self.secondary_codes,
            "method": self.method,
            "raw_response_hash": self.raw_response_hash,
            "review_status": "auto",
            "error": self.error,
        }


def validate_codes(codes: list[str], valid_codes: set[str]) -> tuple[list[str], list[str]]:
    """Split codes into (valid, invalid) against the APS scheme."""
    valid, invalid = [], []
    for c in codes:
        (valid if c in valid_codes else invalid).append(c)
    return valid, invalid


def map_label_with_apertus(
    source: SourceLabel,
    aps_topics: list[ApsTopic],
    client: ApertusClient,
    sample_titles: list[str] | None = None,
) -> MappingResult:
    """Run a single Apertus classification for one source label."""
    messages = build_mapping_prompt(
        source_scheme=source.scheme,
        source_label_de=source.label_de,
        source_label_fr=source.label_fr,
        source_label_it=source.label_it,
        affair_count=source.affair_count,
        aps_topics=aps_topics,
        sample_titles=sample_titles,
    )
    valid_codes = {t.code for t in aps_topics}

    try:
        parsed, raw = client.chat_json(messages=messages, max_tokens=4096)
    except ApertusError as exc:
        return MappingResult(
            source=source, method="apertus", error=f"apertus_error: {exc}"
        )

    primary_raw = parsed.get("primary", []) or []
    secondary_raw = parsed.get("secondary", []) or []
    if not isinstance(primary_raw, list) or not isinstance(secondary_raw, list):
        return MappingResult(
            source=source,
            method="apertus",
            error=f"schema_error: expected lists, got {type(primary_raw).__name__}/"
            f"{type(secondary_raw).__name__}",
            raw_response_hash=raw.content_hash,
        )

    primary, invalid_p = validate_codes([str(c) for c in primary_raw], valid_codes)
    secondary, invalid_s = validate_codes([str(c) for c in secondary_raw], valid_codes)
    invalid = invalid_p + invalid_s
    # Dedupe: drop secondaries that are already primaries
    secondary = [c for c in secondary if c not in set(primary)]

    error_msg = None
    if invalid:
        error_msg = f"invalid_codes: {invalid}"
        logger.warning("Label %r produced invalid APS codes %s", source.label_de, invalid)

    return MappingResult(
        source=source,
        primary_codes=primary,
        secondary_codes=secondary,
        method="apertus",
        raw_response_hash=raw.content_hash,
        error=error_msg,
    )
