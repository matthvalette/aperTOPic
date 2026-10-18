"""Reverse-prompt Apertus to find source labels that cover orphaned APS codes."""

from __future__ import annotations

import logging
from typing import Any

from topic_mapping.apertus_client import ApertusClient, ApertusError
from topic_mapping.classify import MappingResult
from topic_mapping.data_loaders import SourceLabel
from topic_mapping.prompts import ApsTopic, build_reverse_prompt

logger = logging.getLogger(__name__)


def fill_uncovered_codes(
    uncovered_codes: list[str],
    aps_topics: list[ApsTopic],
    existing_results: list[MappingResult],
    client: ApertusClient,
) -> dict[str, list[tuple[str, str]]]:
    """For each uncovered APS code, ask Apertus which source labels cover it.

    Returns
    -------
    dict
        ``{aps_code: [(source_id, relevance), ...]}`` — mergeable additions.
    """
    aps_by_code = {t.code: t for t in aps_topics}
    candidate_labels = [
        {
            "id": f"{r.source.scheme}:{r.source.source_id}",
            "label_de": r.source.label_de,
            "label_fr": r.source.label_fr,
            "label_it": r.source.label_it,
        }
        for r in existing_results
    ]

    additions: dict[str, list[tuple[str, str]]] = {}
    for code in uncovered_codes:
        topic = aps_by_code[code]
        logger.info("Reverse-prompting for uncovered APS %s (%s)", code, topic.topic_de)
        messages = build_reverse_prompt(topic, candidate_labels)
        try:
            parsed, _raw = client.chat_json(messages=messages, max_tokens=1024)
        except ApertusError as exc:
            logger.warning("Reverse prompt failed for %s: %s", code, exc)
            continue

        ids = parsed.get("covering_source_ids", []) or []
        rels = parsed.get("relevance", []) or []
        if not isinstance(ids, list) or not isinstance(rels, list):
            logger.warning("Bad reverse-prompt schema for %s", code)
            continue
        if len(ids) != len(rels):
            logger.warning("Mismatched id/relevance lists for %s", code)
            continue
        additions[code] = [(str(i), str(r)) for i, r in zip(ids, rels, strict=True)]
    return additions


def merge_additions(
    results: list[MappingResult],
    additions: dict[str, list[tuple[str, str]]],
) -> int:
    """Merge reverse-prompt additions into existing results in-place.

    Returns number of edges added.
    """
    by_full_id = {f"{r.source.scheme}:{r.source.source_id}": r for r in results}
    n_added = 0
    for aps_code, pairs in additions.items():
        for source_id, relevance in pairs:
            r = by_full_id.get(source_id)
            if r is None:
                continue
            if relevance == "primary" and aps_code not in r.primary_codes:
                r.primary_codes.append(aps_code)
                n_added += 1
            elif relevance == "secondary" and aps_code not in r.secondary_codes:
                if aps_code not in r.primary_codes:
                    r.secondary_codes.append(aps_code)
                    n_added += 1
    return n_added
