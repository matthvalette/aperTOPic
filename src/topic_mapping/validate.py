"""Validate the mapping against labeled federal affairs and PolitMonitor tags.

Checks:
1. Mapping-applied APS distribution on affairs tagged "Digitalisierung" — should
   be dominated by 6.1.9 (Digitalisierung) and related codes.
2. Coverage stats: what fraction of affairs get ≥1 APS code via the mapping.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "hackapertus"
PARAMETERS_DIR = PROJECT_ROOT / "parameters"

# APS codes expected to dominate digitalisation-tagged affairs
DIGITALISIERUNG_APS = {"6.1.9", "4.4.4", "1.2.2", "7.1.7", "7.2.9"}


def load_mappings(parameters_dir: Path) -> dict[str, dict]:
    """Load all mapping files into a single {source_label_de: entry} dict."""
    all_mappings: dict[str, dict] = {}
    for path in parameters_dir.glob("*_to_aps.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for m in data["mappings"]:
            key = f"{data['metadata']['source_scheme']}::{m['source_label_de']}"
            all_mappings[key] = m
    return all_mappings


def apply_mapping_to_affair(
    topics_de: str, mappings_by_label: dict[str, dict]
) -> tuple[set[str], set[str]]:
    """Apply the mapping to one affair's topic labels."""
    primaries: set[str] = set()
    secondaries: set[str] = set()
    if not topics_de or pd.isna(topics_de):
        return primaries, secondaries
    for topic in str(topics_de).split(" | "):
        topic = topic.strip()
        # Try CHE scheme first
        entry = mappings_by_label.get(f"curia_vista_subject_areas::{topic}")
        if entry:
            primaries.update(entry["aps_primary"])
            secondaries.update(entry["aps_secondary"])
    # Secondaries that are also primaries get promoted
    secondaries -= primaries
    return primaries, secondaries


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=PARAMETERS_DIR / "validation_report.json",
        help="Where to write the JSON report",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s: %(message)s",
    )

    logger.info("Loading mapping files...")
    mappings = load_mappings(PARAMETERS_DIR)
    logger.info("Loaded %d source-label mappings", len(mappings))

    # --- Check 1: coverage on all labeled federal affairs
    logger.info("Loading federal affairs...")
    affairs = pd.read_csv(DATA_DIR / "che_affairs_keywords.csv", encoding="utf-8", low_memory=False)
    affairs = affairs[affairs["topics_de"].notna()]
    logger.info("%d federal affairs with topic labels", len(affairs))

    n_with_primary = 0
    primary_counter: Counter = Counter()
    for _, row in affairs.head(5000).iterrows():  # sample for speed
        p, s = apply_mapping_to_affair(row["topics_de"], mappings)
        if p:
            n_with_primary += 1
            primary_counter.update(p)

    coverage_pct = 100.0 * n_with_primary / len(affairs.head(5000))
    print(f"\nFederal affairs with >=1 primary APS code: {coverage_pct:.1f}%")

    # --- Check 2: PolitMonitor digitalisation sanity
    logger.info("Loading PolitMonitor digitalisation tags...")
    polit = pd.read_csv(DATA_DIR / "politmonitor_digitalisierung.csv", encoding="utf-8")
    polit_che = polit[polit["body_key"] == "CHE"]
    logger.info("%d PolitMonitor-tagged CHE affairs", len(polit_che))

    polit_ids = set(polit_che["openparldata_id"].tolist())
    tagged_affairs = affairs[affairs["openparldata_id"].isin(polit_ids)]
    logger.info("%d tagged affairs have topic labels", len(tagged_affairs))

    digi_primaries: Counter = Counter()
    digi_secondaries: Counter = Counter()
    for _, row in tagged_affairs.iterrows():
        p, s = apply_mapping_to_affair(row["topics_de"], mappings)
        digi_primaries.update(p)
        digi_secondaries.update(s)

    total_digi = sum(digi_primaries.values())
    print(f"\nPolitMonitor digitalisation affairs: {len(tagged_affairs)}")
    print(f"Total primary APS assignments: {total_digi}")
    print("\nTop 10 primary APS codes on digitalisation-tagged affairs:")
    for code, count in digi_primaries.most_common(10):
        marker = "*" if code in DIGITALISIERUNG_APS else " "
        print(f"  {marker} {code}: {count} ({100.0 * count / total_digi:.1f}%)")

    n_digi_hits = sum(digi_primaries[c] for c in DIGITALISIERUNG_APS if c in digi_primaries)
    digi_precision = 100.0 * n_digi_hits / total_digi if total_digi else 0.0
    print(f"\nDigitalisierung-related codes share: {digi_precision:.1f}%")

    # --- Write report
    report = {
        "federal_affairs_sample": 5000,
        "federal_coverage_pct": round(coverage_pct, 2),
        "politmonitor_digitalisierung": {
            "n_tagged_che_affairs": len(polit_che),
            "n_with_labels": len(tagged_affairs),
            "total_primary_assignments": total_digi,
            "top_aps_codes": [
                {"code": c, "count": n, "is_digi": c in DIGITALISIERUNG_APS}
                for c, n in digi_primaries.most_common(20)
            ],
            "digi_related_share_pct": round(digi_precision, 2),
        },
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
