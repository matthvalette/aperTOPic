"""Coverage analysis: ensure every APS code is reachable by at least one source label."""

from __future__ import annotations

import logging
from collections import defaultdict

from topic_mapping.classify import MappingResult
from topic_mapping.prompts import ApsTopic

logger = logging.getLogger(__name__)


def compute_coverage(
    results: list[MappingResult], aps_topics: list[ApsTopic]
) -> dict:
    """Compute which APS codes are covered, and by which source labels.

    Returns
    -------
    dict
        - ``covered_codes``: set of codes appearing in any primary or secondary
        - ``uncovered_codes``: sorted list of codes not covered
        - ``per_code``: dict code → {"primary": [source_ids], "secondary": [source_ids]}
        - ``coverage_pct``: float 0–100
    """
    per_code: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"primary": [], "secondary": []}
    )
    for r in results:
        sid = f"{r.source.scheme}:{r.source.source_id}"
        for c in r.primary_codes:
            per_code[c]["primary"].append(sid)
        for c in r.secondary_codes:
            per_code[c]["secondary"].append(sid)

    all_codes = {t.code for t in aps_topics}
    covered = set(per_code.keys())
    uncovered = sorted(all_codes - covered)

    return {
        "covered_codes": covered,
        "uncovered_codes": uncovered,
        "per_code": dict(per_code),
        "coverage_pct": round(100.0 * len(covered) / len(all_codes), 2),
    }


def coverage_report(cov: dict, aps_topics: list[ApsTopic]) -> str:
    """Human-readable coverage report."""
    by_code = {t.code: t for t in aps_topics}
    lines = [
        f"APS coverage: {cov['coverage_pct']}% "
        f"({len(cov['covered_codes'])}/{len(cov['covered_codes']) + len(cov['uncovered_codes'])})",
        "",
    ]
    if cov["uncovered_codes"]:
        lines.append("Uncovered APS codes:")
        for code in cov["uncovered_codes"]:
            t = by_code[code]
            lines.append(f"  {code}  {t.topic_de} ({t.chapter_de} > {t.domain_de})")
    else:
        lines.append("All APS codes are covered.")
    return "\n".join(lines)
