"""CLI entrypoint: build Curia Vista / cantonal → APS mapping files.

Usage
-----
    python -m topic_mapping.build_mapping [--scheme SCHEME] [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from topic_mapping.apertus_client import ApertusClient, ApertusError
from topic_mapping.classify import MappingResult, map_label_with_apertus
from topic_mapping.coverage import compute_coverage, coverage_report
from topic_mapping.coverage_fill import fill_uncovered_codes, merge_additions
from topic_mapping.data_loaders import (
    SourceLabel,
    load_aps_topics,
    load_cantonal_labels,
    load_curia_vista_labels,
    load_sample_titles_per_label,
)
from topic_mapping.embeddings_fallback import map_label_with_embeddings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "hackapertus"
PARAMETERS_DIR = PROJECT_ROOT / "parameters"


def write_mapping_file(
    results: list[MappingResult],
    scheme: str,
    output_path: Path,
    aps_version: str,
    apertus_model: str | None,
    stats: dict,
) -> None:
    """Write one scheme's mapping JSON."""
    payload = {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_scheme": scheme,
            "target_scheme": f"APS_{aps_version}",
            "apertus_model": apertus_model,
            "stats": stats,
        },
        "mappings": [r.to_dict() for r in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s (%d mappings)", output_path, len(results))


def map_scheme(
    scheme: str,
    labels: list[SourceLabel],
    aps_topics,
    client: ApertusClient | None,
    sample_titles: dict[str, list[str]],
    use_fallback: bool = True,
    limit: int | None = None,
    dry_run: bool = False,
) -> list[MappingResult]:
    """Map all labels of one scheme via Apertus (or fallback)."""
    if limit:
        labels = labels[:limit]
    results: list[MappingResult] = []
    for i, label in enumerate(labels, 1):
        logger.info(
            "[%s %d/%d] %s (%d affairs)",
            scheme,
            i,
            len(labels),
            label.label_de,
            label.affair_count,
        )
        if dry_run:
            results.append(
                MappingResult(source=label, method="dry_run", primary_codes=[], secondary_codes=[])
            )
            continue

        titles = sample_titles.get(label.label_de, [])
        result: MappingResult | None = None
        if client is not None:
            result = map_label_with_apertus(label, aps_topics, client, sample_titles=titles)
            if result.error and "apertus_error" in result.error and use_fallback:
                logger.warning("Apertus failed for %s; using embeddings fallback", label.label_de)
                result = map_label_with_embeddings(label, aps_topics)
        elif use_fallback:
            result = map_label_with_embeddings(label, aps_topics)

        if result is None:
            result = MappingResult(source=label, method="none", error="no_method_available")
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scheme",
        choices=["che", "sg", "tg", "zh", "all"],
        default="all",
        help="Which source scheme to map",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit labels per scheme (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls, just test data plumbing")
    parser.add_argument("--no-fallback", action="store_true", help="Disable embeddings fallback")
    parser.add_argument("--no-coverage-fill", action="store_true", help="Skip reverse-prompt coverage pass")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    logger.info("Loading APS topics...")
    aps_topics = load_aps_topics(DATA_DIR / "aps_topics.xlsx")
    logger.info("Loaded %d APS topics", len(aps_topics))

    aps_version = "2026-10-18"  # from the file snapshot date

    client: ApertusClient | None = None
    apertus_model: str | None = None
    if not args.dry_run:
        try:
            client = ApertusClient()
            apertus_model = client.model
            logger.info("Apertus client ready (model=%s)", apertus_model)
        except ApertusError as exc:
            logger.warning("Apertus unavailable: %s. Falling back to embeddings.", exc)
            if args.no_fallback:
                logger.error("Fallback disabled; aborting.")
                return 2

    all_results: list[MappingResult] = []
    scheme_outputs: dict[str, Path] = {}

    # Federal Curia Vista
    if args.scheme in ("che", "all"):
        labels = load_curia_vista_labels(DATA_DIR / "che_topics_vocabulary.csv")
        titles = load_sample_titles_per_label(DATA_DIR / "che_affairs_keywords.csv")
        results = map_scheme(
            "curia_vista_subject_areas",
            labels,
            aps_topics,
            client,
            titles,
            use_fallback=not args.no_fallback,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        scheme_outputs["curia_vista_subject_areas"] = PARAMETERS_DIR / "curia_vista_to_aps.json"
        all_results.extend(results)

    # Cantonal
    if args.scheme in ("sg", "tg", "zh", "all"):
        cantonal = load_cantonal_labels(DATA_DIR / "cantonal_keywords_vocabulary.csv")
        cantonal_affairs_path = DATA_DIR / "cantonal_affairs_keywords.csv"
        for body_key, scheme_name, out_name in (
            ("SG", "cantonal_SG", "cantonal_sg_to_aps.json"),
            ("TG", "cantonal_TG", "cantonal_tg_to_aps.json"),
            ("ZH", "cantonal_ZH", "cantonal_zh_to_aps.json"),
        ):
            if args.scheme not in (body_key.lower(), "all"):
                continue
            labels = cantonal[body_key]
            titles = load_sample_titles_per_label(cantonal_affairs_path, body_key=body_key)
            results = map_scheme(
                scheme_name,
                labels,
                aps_topics,
                client,
                titles,
                use_fallback=not args.no_fallback,
                limit=args.limit,
                dry_run=args.dry_run,
            )
            scheme_outputs[scheme_name] = PARAMETERS_DIR / out_name
            all_results.extend(results)

    # Write per-scheme files
    if not args.dry_run:
        for scheme, path in scheme_outputs.items():
            scheme_results = [r for r in all_results if r.source.scheme == scheme]
            stats = {
                "n_labels": len(scheme_results),
                "n_with_primary": sum(1 for r in scheme_results if r.primary_codes),
                "n_with_error": sum(1 for r in scheme_results if r.error),
                "mean_aps_per_label": round(
                    sum(len(r.primary_codes) + len(r.secondary_codes) for r in scheme_results)
                    / max(1, len(scheme_results)),
                    2,
                ),
            }
            write_mapping_file(scheme_results, scheme, path, aps_version, apertus_model, stats)

    # Coverage analysis + optional reverse-prompt fill
    cov = compute_coverage(all_results, aps_topics)
    if (
        not args.dry_run
        and not args.no_coverage_fill
        and cov["uncovered_codes"]
        and client is not None
    ):
        logger.info(
            "Coverage pass: %d uncovered APS codes — reverse-prompting",
            len(cov["uncovered_codes"]),
        )
        additions = fill_uncovered_codes(
            cov["uncovered_codes"], aps_topics, all_results, client
        )
        n_added = merge_additions(all_results, additions)
        logger.info("Coverage fill added %d edges", n_added)
        # Recompute coverage
        cov = compute_coverage(all_results, aps_topics)
        # Rewrite per-scheme files with merged edges
        for scheme, path in scheme_outputs.items():
            scheme_results = [r for r in all_results if r.source.scheme == scheme]
            stats = {
                "n_labels": len(scheme_results),
                "n_with_primary": sum(1 for r in scheme_results if r.primary_codes),
                "n_with_error": sum(1 for r in scheme_results if r.error),
                "mean_aps_per_label": round(
                    sum(len(r.primary_codes) + len(r.secondary_codes) for r in scheme_results)
                    / max(1, len(scheme_results)),
                    2,
                ),
            }
            write_mapping_file(scheme_results, scheme, path, aps_version, apertus_model, stats)

    report = coverage_report(cov, aps_topics)
    print("\n" + report)

    if not args.dry_run:
        metadata_path = PARAMETERS_DIR / "mapping_metadata.json"
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "apertus_model": apertus_model,
            "aps_version": aps_version,
            "schemes": list(scheme_outputs.keys()),
            "coverage": {
                "coverage_pct": cov["coverage_pct"],
                "n_covered": len(cov["covered_codes"]),
                "n_total": len(cov["covered_codes"]) + len(cov["uncovered_codes"]),
                "uncovered_codes": cov["uncovered_codes"],
            },
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Wrote %s", metadata_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
