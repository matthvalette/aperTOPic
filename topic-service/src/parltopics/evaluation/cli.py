"""Evaluate Jev on the labelled data, without the HTTP service.

    uv run parltopics-eval subject-areas --n 300 --languages de fr it
    uv run parltopics-eval digitalisation --n 300

Results go to evaluation_runs/<time>_<task>/ (report.md, results.json). Jev answers are cached
in evaluation_runs/cache/, so a rerun with the same questions costs nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from ..adapters.jev import JevTopicClassifier
from ..adapters.taxonomies import CURIA, DIGITALISATION, LabelledDataTaxonomies
from ..config import PROJECT_ROOT, get_settings
from . import metrics
from .datasets import digitalisation_sample, subject_area_sample
from .runner import PredictionCache, predict

RUNS = PROJECT_ROOT / "evaluation_runs"
PRICE_PER_MTOK = 0.042  # USD per million input tokens, jev-1.13 (docs.typesafe.ai/models)


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


async def _classifier(settings, model: str) -> tuple[AsyncTypeSafeClient, JevTopicClassifier]:
    if not settings.typesafe_api_key:
        raise SystemExit("Set TYPESAFE_API_KEY in .env")
    client = AsyncTypeSafeClient(
        api_key=settings.typesafe_api_key.get_secret_value(),
        model=model,
        timeout=settings.typesafe_timeout_s,
        retry=RetryPolicy(max_retries=5),
    )
    classifier = JevTopicClassifier(
        client,
        model=model,
        max_concurrency=settings.typesafe_max_concurrency,
        max_section_chars=settings.max_section_chars,
        max_state_chars=settings.max_state_chars,
    )
    return client, classifier


def _cost_lines(classifier: JevTopicClassifier, docs_per_language: int, languages: int) -> list[str]:
    if not classifier.requests:
        return ["- All answers came from the cache; no new requests."]
    per_request = classifier.input_tokens / classifier.requests
    usd = classifier.input_tokens / 1e6 * PRICE_PER_MTOK
    per_300k = per_request * 300_000 / 1e6 * PRICE_PER_MTOK
    return [
        f"- New Jev requests: {classifier.requests}, input tokens: {classifier.input_tokens:,} "
        f"({per_request:,.0f} per affair), cost about ${usd:.3f}.",
        f"- At this size, classifying 300,000 affairs once would cost about ${per_300k:,.0f}.",
    ]


async def run_subject_areas(args: argparse.Namespace) -> Path:
    settings = get_settings()
    taxonomy = LabelledDataTaxonomies(settings.data_dir).get(CURIA)
    names = {t.id: t.name for t in taxonomy.topics}
    languages = tuple(args.languages)
    print(f"Loading {args.n} labelled federal affairs ({args.years[0]}–{args.years[1]})…", flush=True)
    sample = subject_area_sample(
        settings.data_dir, n=args.n, years=tuple(args.years), seed=args.seed, require_languages=languages
    )
    dev = [a for a in sample if a.split == "dev"]
    test = [a for a in sample if a.split == "test"]
    print(f"{len(sample)} affairs: {len(dev)} dev (threshold tuning), {len(test)} test", flush=True)

    client, classifier = await _classifier(settings, args.model)
    cache = PredictionCache(RUNS / "cache" / "subject_areas.jsonl")
    per_language: dict[str, dict] = {}
    async with client:
        for lang in languages:
            documents = [a.document(lang) for a in sample]
            probs, stats = await predict(
                documents, taxonomy, classifier, cache, model=args.model, label=lang
            )
            print(f"[{lang}] {stats.requested} new, {stats.cached} cached, {len(stats.failed)} failed, "
                  f"{stats.seconds:.0f}s", flush=True)
            dev_p = [probs[str(a.affair_id)] for a in dev if str(a.affair_id) in probs]
            dev_g = [a.gold for a in dev if str(a.affair_id) in probs]
            test_p = [probs[str(a.affair_id)] for a in test if str(a.affair_id) in probs]
            test_g = [a.gold for a in test if str(a.affair_id) in probs]
            tuned = metrics.best_threshold(dev_p, dev_g)
            per_language[lang] = {
                "threshold": tuned,
                "test_tuned": metrics.multilabel_at_threshold(test_p, test_g, tuned),
                "test_at_0_5": metrics.multilabel_at_threshold(test_p, test_g, 0.5),
                "test_ranking": metrics.ranking_metrics(test_p, test_g),
                "per_topic_auc": {
                    k: metrics.auc([p[k] for p, g in zip(test_p, test_g) if k in g],
                                   [p[k] for p, g in zip(test_p, test_g) if k not in g])
                    for k in names
                },
                "failed": stats.failed,
                "predictions": {
                    str(a.affair_id): {"number": a.number, "gold": sorted(a.gold), "probs": probs.get(str(a.affair_id))}
                    for a in sample
                },
            }
    baseline = metrics.frequency_baseline([a.gold for a in dev], [a.gold for a in test])

    # ---------- report ----------
    lines = [
        "# Jev on Curia Vista subject areas",
        "",
        f"- Model `{args.model}`, {len(taxonomy.topics)} subject areas, one Noul per subject area.",
        f"- {len(sample)} federal affairs submitted {args.years[0]}–{args.years[1]} (seed {args.seed}), "
        f"title + submitted text + reasoning. Dev {len(dev)} / test {len(test)}.",
        f"- Gold: {sum(len(a.gold) for a in test) / max(len(test), 1):.2f} subject areas per test affair.",
        "- The threshold is tuned on dev (best micro-F1) and every number below is on test.",
        "",
        "## Overall (test set)",
        "",
        "| Language | Threshold | Micro P | Micro R | Micro F1 | Macro F1 | Exact match | Jaccard | Top-1 correct | Recall@3 | Macro AUC |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for lang, r in per_language.items():
        m, k = r["test_tuned"], r["test_ranking"]
        lines.append(
            f"| {lang} | {r['threshold']:.2f} | {_pct(m['micro_precision'])} | {_pct(m['micro_recall'])} | "
            f"**{_pct(m['micro_f1'])}** | {_pct(m['macro_f1'])} | {_pct(m['exact_match'])} | "
            f"{m['mean_jaccard']:.2f} | {_pct(k['top1_accuracy'])} | {_pct(k['recall_at_3'])} | "
            f"{k['macro_auc']:.3f} |"
        )
    first = languages[0]
    m05 = per_language[first]["test_at_0_5"]
    lines += [
        "",
        f"At the default threshold 0.5 ({first}): micro-F1 {_pct(m05['micro_f1'])}, "
        f"{m05['labels_per_affair_predicted']:.2f} predicted vs {m05['labels_per_affair_gold']:.2f} gold labels per affair.",
        "",
        f"Baseline, always predicting the {baseline['k']} most frequent subject areas "
        f"({', '.join(names[t] for t in baseline['topics'])}): micro-F1 {_pct(baseline['micro_f1'])}, "
        f"macro-F1 {_pct(baseline['macro_f1'])}.",
        "",
        f"## Per subject area (test, {first}, threshold {per_language[first]['threshold']:.2f})",
        "",
        "| Subject area | Gold | Precision | Recall | F1 | AUC |",
        "|---|---|---|---|---|---|",
    ]
    rows = per_language[first]["test_tuned"]["per_topic"]
    aucs = per_language[first]["per_topic_auc"]
    for topic_id in sorted(names, key=lambda t: -rows.get(t, {"support": 0})["support"]):
        row = rows.get(topic_id, {"support": 0, "precision": 0, "recall": 0, "f1": 0})
        auc_value = aucs.get(topic_id)
        lines.append(
            f"| {names[topic_id]} | {row['support']} | {_pct(row['precision'])} | {_pct(row['recall'])} | "
            f"{_pct(row['f1'])} | {'–' if auc_value is None else f'{auc_value:.3f}'} |"
        )
    lines += ["", "## Cost", ""] + _cost_lines(classifier, len(sample), len(languages))

    out = RUNS / f"{datetime.now():%Y%m%d-%H%M%S}_subject_areas_{args.model}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "results.json").write_text(
        json.dumps({"args": vars(args), "baseline": baseline, "languages": per_language}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("\n" + "\n".join(lines))
    return out


async def run_digitalisation(args: argparse.Namespace) -> Path:
    settings = get_settings()
    taxonomy = LabelledDataTaxonomies(settings.data_dir).get(DIGITALISATION)
    print(f"Loading {args.n} federal affairs ({args.years[0]}–{args.years[1]}), half tagged…", flush=True)
    positives, negatives = digitalisation_sample(settings.data_dir, n=args.n, years=tuple(args.years), seed=args.seed)
    sample = positives + negatives
    dev = [a for a in sample if a.split == "dev"]
    test = [a for a in sample if a.split == "test"]
    client, classifier = await _classifier(settings, args.model)
    cache = PredictionCache(RUNS / "cache" / "digitalisation.jsonl")
    async with client:
        probs, stats = await predict(
            [a.document("de") for a in sample], taxonomy, classifier, cache, model=args.model, label="de"
        )
    print(f"[de] {stats.requested} new, {stats.cached} cached, {len(stats.failed)} failed, {stats.seconds:.0f}s")

    def scores(rows):
        kept = [a for a in rows if str(a.affair_id) in probs]
        return [probs[str(a.affair_id)]["digitalisation"] for a in kept], [bool(a.gold) for a in kept]

    dev_s, dev_y = scores(dev)
    test_s, test_y = scores(test)
    grid = [round(0.05 * i, 2) for i in range(1, 20)]
    tuned = max(grid, key=lambda t: (metrics.binary_metrics(dev_s, dev_y, t)["f1"], -abs(t - 0.5)))
    at_tuned = metrics.binary_metrics(test_s, test_y, tuned)
    at_half = metrics.binary_metrics(test_s, test_y, 0.5)
    lines = [
        "# Jev on the PolitMonitor “Digitalisierung” tag",
        "",
        f"- Model `{args.model}`, one Noul, German texts of federal affairs {args.years[0]}–{args.years[1]}.",
        f"- {len(positives)} tagged and {len(negatives)} untagged affairs; dev {len(dev)} / test {len(test)}.",
        "- Untagged affairs count as negatives, but editors miss some, so precision is a lower bound.",
        "",
        "| Threshold | Precision | Recall | F1 | Accuracy | AUC |",
        "|---|---|---|---|---|---|",
    ]
    for m in (at_half, at_tuned):
        lines.append(
            f"| {m['threshold']:.2f}{' (tuned on dev)' if m is at_tuned else ''} | {_pct(m['precision'])} | "
            f"{_pct(m['recall'])} | **{_pct(m['f1'])}** | {_pct(m['accuracy'])} | {m['auc']:.3f} |"
        )
    false_pos = sorted(
        ((probs[str(a.affair_id)]["digitalisation"], a.number) for a in test if not a.gold and str(a.affair_id) in probs),
        reverse=True,
    )[:8]
    lines += [
        "",
        f"Confusion at {tuned:.2f}: {at_tuned['confusion']}.",
        "",
        "Untagged affairs Jev scores highest (candidates for missed tags): "
        + ", ".join(f"{num} ({p:.2f})" for p, num in false_pos),
        "",
        "## Cost",
        "",
    ] + _cost_lines(classifier, len(sample), 1)
    out = RUNS / f"{datetime.now():%Y%m%d-%H%M%S}_digitalisation_{args.model}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "results.json").write_text(
        json.dumps(
            {
                "args": vars(args),
                "threshold": tuned,
                "test_tuned": at_tuned,
                "test_at_0_5": at_half,
                "failed": stats.failed,
                "predictions": {
                    str(a.affair_id): {"number": a.number, "tagged": bool(a.gold), "p": probs.get(str(a.affair_id), {}).get("digitalisation")}
                    for a in sample
                },
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("\n" + "\n".join(lines))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="parltopics-eval", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="task", required=True)
    sa = sub.add_parser("subject-areas", help="Curia Vista subject areas (28, multi-label)")
    sa.add_argument("--n", type=int, default=300)
    sa.add_argument("--languages", nargs="+", default=["de"], choices=["de", "fr", "it"])
    sa.add_argument("--years", nargs=2, type=int, default=[2018, 2026])
    sa.add_argument("--seed", type=int, default=7)
    dg = sub.add_parser("digitalisation", help="PolitMonitor digitalisation tag (binary)")
    dg.add_argument("--n", type=int, default=300)
    dg.add_argument("--years", nargs=2, type=int, default=[2019, 2023])
    dg.add_argument("--seed", type=int, default=7)
    for p in (sa, dg):
        p.add_argument("--model", default=None, help="Jev model id, e.g. jev-1.13.0 or jev-1.14.0")
    args = parser.parse_args()
    args.model = args.model or get_settings().typesafe_model
    runner = run_subject_areas if args.task == "subject-areas" else run_digitalisation
    out = asyncio.run(runner(args))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
