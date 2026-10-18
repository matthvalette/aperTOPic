"""Build notebooks/01_eda.ipynb programmatically.

Keeps the notebook JSON readable in this script rather than embedding
a giant JSON blob. Run once with: ``python scripts/build_eda_notebook.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

CELL_MD = "markdown"
CELL_CODE = "code"


def md(source: str) -> dict:
    return {
        "cell_type": CELL_MD,
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def code(source: str) -> dict:
    return {
        "cell_type": CELL_CODE,
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


CELLS: list[dict] = []

# ---------------------------------------------------------------- header
CELLS.append(md("""# 01 — Exploratory Data Analysis of OpenParlData

**Purpose.** Build a comprehensive picture of the parliamentary affairs
corpus available under `data/`, in preparation for the topic-classification
service. We answer:

- Which parliaments are represented, and how many affairs does each have?
- What harmonized affair types (Motion, Postulate, Interpellation, ...)
  are used by each parliament?
- What languages are titles and full texts available in?
- How long are the texts / documents / speeches, and how are they
  distributed across bodies and types?
- For the labelled HackApertus subset: what subject-area schemes exist,
  and how are affairs distributed across them?
- For the DVS use case: how are the 3,433 PolitMonitor-tagged
  digitalisation affairs distributed across parliaments and time?

**Inputs.**

- `data/exports/index.json` — top-level corpus inventory
- `data/exports/affairs.ndjson.gz` — 326,396 affairs (master table)
- `data/exports/texts/*.ndjson.gz` — 226,078 affair texts
- `data/exports/docs/*.ndjson.gz` — 910,298 documents (Tika-extracted text)
- `data/exports/speeches/*.ndjson.gz` — 552,563 speeches
- `data/exports/news/*.ndjson.gz` — 339,562 news items
- `data/hackapertus/*.csv / .xlsx` — labelled subsets (CHE + SG/TG/Zug/ZH,
  PolitMonitor digitalisation, APS scheme)

**Outputs.**

- `data/eda/affairs_by_body_type.parquet` — body × type counts
- `data/eda/texts_stats.parquet` — body × text-type × language length stats
- `data/eda/docs_stats.parquet` — body-level docs aggregates
- `data/eda/speeches_stats.parquet` — body-level speeches aggregates
- `data/eda/news_stats.parquet` — body-level news aggregates
- `Log.md` entry per AGENTS.md §8

**Conventions.** Per AGENTS.md §6: `PROJECT_ROOT` is derived from the
notebook location; all paths are `pathlib.Path`; reusable logic lives in
`src/eda_io.py`; HTML stripping is approximate (regex-based); the heavy
scans cache their aggregated output so re-runs are fast (set
`USE_CACHE=False` to force a rescan)."""))

# ---------------------------------------------------------------- setup
CELLS.append(md("## Setup"))
CELLS.append(code("""from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import gzip
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# Locate the project root regardless of where the kernel is started.
NOTEBOOK_DIR = Path.cwd().resolve()
PROJECT_ROOT = NOTEBOOK_DIR if (NOTEBOOK_DIR / "data").is_dir() else NOTEBOOK_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from eda_io import LengthAccumulator, iter_ndjson_gz, strip_html, text_stats

DATA_DIR = PROJECT_ROOT / "data"
EXPORTS_DIR = DATA_DIR / "exports"
HACK_DIR = DATA_DIR / "hackapertus"
EDA_OUT = DATA_DIR / "eda"
EDA_OUT.mkdir(parents=True, exist_ok=True)

USE_CACHE = True  # set False to force full rescan of texts/docs/speeches/news

sns.set_theme(style="whitegrid")
plt.rcParams["figure.figsize"] = (11, 5)
plt.rcParams["axes.titlesize"] = 13

print(f"PROJECT_ROOT = {PROJECT_ROOT}")
print(f"DATA_DIR     = {DATA_DIR}")
print(f"EDA_OUT      = {EDA_OUT}")
print(f"USE_CACHE    = {USE_CACHE}")
"""))

# ---------------------------------------------------------------- section 1
CELLS.append(md("""## 1. Corpus overview

Read `index.json` — the machine-generated inventory of the export. This
gives us row counts and gzipped sizes for every entity without scanning
the payloads."""))
CELLS.append(code("""t0 = time.perf_counter()
index_path = EXPORTS_DIR / "index.json"
with index_path.open("r", encoding="utf-8") as fh:
    index = json.load(fh)

rows = []
for entry in index["files"]:
    if entry.get("type") == "single":
        rows.append({
            "entity": entry["entity"],
            "files": 1,
            "rows": entry.get("row_count"),
            "size_mb": entry["size"] / 1024 / 1024,
        })
    else:
        rows.append({
            "entity": entry["entity"],
            "files": entry["file_count"],
            "rows": entry.get("total_row_count"),
            "size_mb": entry["total_size"] / 1024 / 1024,
        })

corpus_overview = (
    pd.DataFrame(rows)
    .sort_values("size_mb", ascending=False)
    .reset_index(drop=True)
)
corpus_overview.index += 1
print(f"Generated at: {index['generated_at']}")
print(f"Loaded in {time.perf_counter() - t0:.2f}s")
corpus_overview"""))

CELLS.append(code("""ax = corpus_overview.plot.barh(x="entity", y="size_mb", legend=False,
                                title="Corpus size by entity (gzipped MB)")
ax.invert_yaxis()
ax.set_xlabel("MB (gzipped)")
ax.set_ylabel("")
plt.tight_layout()
plt.show()"""))

# ---------------------------------------------------------------- section 2
CELLS.append(md("""## 2. Affairs by parliament

Load `affairs.ndjson.gz` (326k rows, ~49 MB gzipped). This is the master
table of every political affair tracked by OpenParlData. We keep only the
columns needed for downstream aggregation."""))
CELLS.append(code("""t0 = time.perf_counter()
AFFAIRS_PATH = EXPORTS_DIR / "affairs.ndjson.gz"

keep_cols = [
    "id", "body_key", "type_harmonized_en", "begin_date", "end_date",
    "title_de", "title_fr", "title_it", "title_rm",
]
rows = []
for rec in iter_ndjson_gz(AFFAIRS_PATH):
    rows.append({c: rec.get(c) for c in keep_cols})
affairs = pd.DataFrame(rows)
# Replace the "None" string sentinel (OpenParlData exports None as the
# string "None" for some columns) with real NA.
affairs = affairs.replace({"None": pd.NA, "": pd.NA})
affairs["begin_date"] = pd.to_datetime(affairs["begin_date"], errors="coerce")
print(f"Loaded {len(affairs):,} affairs in {time.perf_counter() - t0:.1f}s")
print(f"Date range: {affairs['begin_date'].min()} -> {affairs['begin_date'].max()}")
print(f"Distinct bodies: {affairs['body_key'].nunique()}")
affairs.head(3)"""))

CELLS.append(code("""affairs_per_body = (
    affairs.groupby("body_key", dropna=False)
    .agg(
        n_affairs=("id", "count"),
        first_affair=("begin_date", "min"),
        last_affair=("begin_date", "max"),
    )
    .sort_values("n_affairs", ascending=False)
)
print(f"Top 20 bodies (out of {len(affairs_per_body)}):")
affairs_per_body.head(20)"""))

CELLS.append(code("""top_n = 20
top_bodies = affairs_per_body.head(top_n)
ax = top_bodies["n_affairs"].plot.barh(title=f"Top {top_n} parliaments by affair count")
ax.invert_yaxis()
ax.set_xlabel("Affairs")
ax.set_ylabel("body_key")
for i, v in enumerate(top_bodies["n_affairs"]):
    ax.text(v, i, f" {v:,}", va="center", fontsize=9)
plt.tight_layout()
plt.show()"""))

# ---------------------------------------------------------------- section 3
CELLS.append(md("""## 3. Body × harmonized-type matrix

Cross-tabulate `body_key` × `type_harmonized_en` to see which parliaments
actually use which instrument types. Restricted to the top 15 bodies and
top 10 types for readability."""))
CELLS.append(code("""t0 = time.perf_counter()
body_type = (
    affairs.groupby(["body_key", "type_harmonized_en"], dropna=False)
    .size()
    .rename("n")
    .reset_index()
)
body_type.to_parquet(EDA_OUT / "affairs_by_body_type.parquet", index=False)

top_bodies_list = affairs_per_body.head(15).index.tolist()
top_types_list = (
    affairs["type_harmonized_en"].value_counts().head(10).index.tolist()
)
matrix = (
    body_type[
        body_type["body_key"].isin(top_bodies_list)
        & body_type["type_harmonized_en"].isin(top_types_list)
    ]
    .pivot(index="body_key", columns="type_harmonized_en", values="n")
    .reindex(index=top_bodies_list, columns=top_types_list)
    .fillna(0)
    .astype(int)
)
print(f"Matrix computed in {time.perf_counter() - t0:.2f}s")
matrix"""))

CELLS.append(code("""fig, ax = plt.subplots(figsize=(12, 7))
sns.heatmap(
    np.log10(matrix + 1),
    annot=matrix,
    fmt=",",
    cmap="viridis",
    cbar_kws={"label": "log10(count+1)"},
    ax=ax,
)
ax.set_title("Body × harmonized type — affair counts (log-scaled colour, raw count labels)")
ax.set_xlabel("Harmonized affair type")
ax.set_ylabel("body_key")
plt.xticks(rotation=30, ha="right")
plt.tight_layout()
plt.show()"""))

# ---------------------------------------------------------------- section 4
CELLS.append(md("""## 4. Language coverage of affair titles

An affair may have titles in any subset of {de, fr, it, rm}. We count
non-null titles per language, grouped by body. Note: this is NOT the
language of full texts (see §6 for that)."""))
CELLS.append(code("""lang_cols = ["title_de", "title_fr", "title_it", "title_rm"]
lang_per_body = (
    affairs.groupby("body_key")[lang_cols]
    .apply(lambda df: df.notna().sum())
    .rename(columns={c: c.replace("title_", "titles_") for c in lang_cols})
)
lang_per_body["n_affairs"] = affairs_per_body["n_affairs"]
for col in [c for c in lang_per_body.columns if c.startswith("titles_")]:
    lang_per_body[f"{col}_pct"] = (lang_per_body[col] / lang_per_body["n_affairs"] * 100).round(1)

top_lang = lang_per_body.loc[affairs_per_body.head(15).index]
top_lang"""))

CELLS.append(code("""fig, ax = plt.subplots(figsize=(11, 6))
langs = ["titles_de", "titles_fr", "titles_it", "titles_rm"]
labels = ["de", "fr", "it", "rm"]
colors = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd"]
data = top_lang[langs].values
data_pct = data / data.sum(axis=1, keepdims=True)
left = np.zeros(len(top_lang))
for i, (lab, col) in enumerate(zip(labels, colors)):
    ax.barh(top_lang.index, data_pct[:, i], left=left, label=lab, color=col)
    left += data_pct[:, i]
ax.invert_yaxis()
ax.set_xlim(0, 1)
ax.set_xlabel("Share of affairs with a title in this language")
ax.set_title("Title language coverage per body (top 15)")
ax.legend(title="Language", ncol=4, loc="lower right")
plt.tight_layout()
plt.show()"""))

# ---------------------------------------------------------------- section 5
CELLS.append(md("""## 5. Affair-type deep dive

For the top 5 harmonized types (Question, Interpellation, Government
affairs, Motion, Postulate): distribution across bodies and average
title length per language."""))
CELLS.append(code("""top5_types = (
    affairs["type_harmonized_en"].value_counts().head(6).index.tolist()
)
# Drop the None sentinel if present (it represents unharmonized rows)
top5_types = [t for t in top5_types if pd.notna(t)][:5]

for t in top5_types:
    sub = affairs[affairs["type_harmonized_en"] == t]
    print(f"\\n=== {t}  ({len(sub):,} affairs, {sub['body_key'].nunique()} bodies) ===")
    print(sub["body_key"].value_counts().head(8).to_string())"""))

CELLS.append(code("""# Title length per type, on the German title (most complete)
affairs["title_de_len"] = affairs["title_de"].fillna("").str.len()
title_len = (
    affairs[affairs["type_harmonized_en"].isin(top5_types)]
    .groupby("type_harmonized_en")["title_de_len"]
    .describe()[["count", "mean", "50%", "max"]]
    .rename(columns={"50%": "median"})
    .round(0)
    .astype(int)
)
title_len"""))

# ---------------------------------------------------------------- section 6
CELLS.append(md("""## 6. Full scan — affair texts

Stream every `texts_*.ndjson.gz` and aggregate `(body_key, text_type,
language)` × length stats. Persisted to
`data/eda/texts_stats.parquet` so re-runs are instant.

Text types come from the source systems (e.g. `Eingereichter Text`,
`Antwort BR / Büro`, `Begründung`). We use `type_de` as the canonical
label because it's the most populated."""))
CELLS.append(code("""TEXTS_CACHE = EDA_OUT / "texts_stats.parquet"
TEXTS_DIR = EXPORTS_DIR / "texts"

if USE_CACHE and TEXTS_CACHE.exists():
    texts_stats = pd.read_parquet(TEXTS_CACHE)
    print(f"Loaded from cache: {TEXTS_CACHE.name} ({len(texts_stats)} rows)")
else:
    t0 = time.perf_counter()
    # key: (body_key, type_de, language)
    accumulators: dict[tuple[str, str, str], LengthAccumulator] = defaultdict(LengthAccumulator)
    total_rows = 0
    files = sorted(TEXTS_DIR.glob("texts_*.ndjson.gz"))
    for fp in files:
        file_rows = 0
        for rec in iter_ndjson_gz(fp):
            body = rec.get("body_key") or "UNKNOWN"
            type_de = rec.get("type_de") or "(untyped)"
            for lang in ("de", "fr", "it", "rm"):
                text = rec.get(f"text_{lang}")
                if text and text != "None":
                    n_chars, _ = text_stats(text)
                    if n_chars > 0:
                        accumulators[(body, type_de, lang)].add(n_chars)
            file_rows += 1
        total_rows += file_rows
        print(f"  {fp.name}: {file_rows:,} rows")
    rows = []
    for (body, type_de, lang), acc in accumulators.items():
        s = acc.summary()
        rows.append({"body_key": body, "type_de": type_de, "language": lang, **s})
    texts_stats = pd.DataFrame(rows)
    texts_stats.to_parquet(TEXTS_CACHE, index=False)
    print(f"Scanned {total_rows:,} text rows in {time.perf_counter() - t0:.1f}s")
    print(f"Wrote {TEXTS_CACHE.name} ({len(texts_stats)} aggregated rows)")

texts_stats.head()"""))

CELLS.append(code("""# Overall per-body text volume and length (German text as reference)
per_body_de = (
    texts_stats[texts_stats["language"] == "de"]
    .groupby("body_key")
    .agg(total_texts=("count", "sum"), mean_chars=("mean", "mean"), p50_chars=("p50", "mean"))
    .sort_values("total_texts", ascending=False)
)
per_body_de["mean_chars"] = per_body_de["mean_chars"].round(0).astype(int)
per_body_de["p50_chars"] = per_body_de["p50_chars"].round(0).astype(int)
print("Top 15 bodies by German-text volume:")
per_body_de.head(15)"""))

CELLS.append(code("""# Text type distribution for CHE (federal)
che_types = (
    texts_stats[(texts_stats["body_key"] == "CHE") & (texts_stats["language"] == "de")]
    .sort_values("count", ascending=False)
    .head(10)
)
fig, ax = plt.subplots(figsize=(10, 4))
ax.barh(che_types["type_de"], che_types["count"], color="#1f77b4")
ax.invert_yaxis()
ax.set_xlabel("Number of texts")
ax.set_title("CHE — top 10 text types (German)")
for i, v in enumerate(che_types["count"]):
    ax.text(v, i, f" {int(v):,}", va="center", fontsize=9)
plt.tight_layout()
plt.show()"""))

# ---------------------------------------------------------------- section 7
CELLS.append(md("""## 7. Full scan — documents

Stream every `docs_*.ndjson.gz` (~5.5 GB gzipped, 910k rows). Each row
represents a document attached to an affair (or news / meeting). Key
fields:

- `format` — MIME type (`application/pdf`, `text/html`, ...)
- `language` — language tag (mostly `de` / `fr` / `it`)
- `size` — original document bytes
- `text` — Tika-extracted text (may be empty for scans)
- `parent_type` — what the doc is attached to (`affair`, `news`, ...)
- `category_harmonized` — broad document category

We aggregate per body: document count, format distribution, language
distribution, size stats, extracted-text length stats."""))
CELLS.append(code("""DOCS_CACHE = EDA_OUT / "docs_stats.parquet"
DOCS_DIR = EXPORTS_DIR / "docs"

if USE_CACHE and DOCS_CACHE.exists():
    docs_stats = pd.read_parquet(DOCS_CACHE)
    print(f"Loaded from cache: {DOCS_CACHE.name} ({len(docs_stats)} rows)")
else:
    t0 = time.perf_counter()
    body_counter: Counter[str] = Counter()
    format_counter: Counter[tuple[str, str]] = Counter()      # (body, format)
    lang_counter: Counter[tuple[str, str]] = Counter()        # (body, language)
    parent_counter: Counter[tuple[str, str]] = Counter()      # (body, parent_type)
    cat_counter: Counter[tuple[str, str]] = Counter()         # (body, category_harmonized)
    size_acc: dict[str, LengthAccumulator] = defaultdict(LengthAccumulator)
    text_len_acc: dict[str, LengthAccumulator] = defaultdict(LengthAccumulator)
    files = sorted(DOCS_DIR.glob("docs_*.ndjson.gz"))
    total_rows = 0
    for i, fp in enumerate(files, 1):
        file_rows = 0
        for rec in iter_ndjson_gz(fp):
            body = rec.get("body_key") or "UNKNOWN"
            body_counter[body] += 1
            fmt = rec.get("format") or "(unknown)"
            format_counter[(body, fmt)] += 1
            lang = rec.get("language") or "(none)"
            lang_counter[(body, lang)] += 1
            parent = rec.get("parent_type") or "(none)"
            parent_counter[(body, parent)] += 1
            cat = rec.get("category_harmonized") or "(uncategorized)"
            cat_counter[(body, cat)] += 1
            size_raw = rec.get("size")
            try:
                size_val = int(size_raw) if size_raw not in (None, "None", "") else 0
            except (TypeError, ValueError):
                size_val = 0
            if size_val > 0:
                size_acc[body].add(size_val)
            text = rec.get("text")
            if text and text != "None":
                n_chars, _ = text_stats(text)
                if n_chars > 0:
                    text_len_acc[body].add(n_chars)
            file_rows += 1
        total_rows += file_rows
        if i % 10 == 0 or i == len(files):
            elapsed = time.perf_counter() - t0
            print(f"  [{i:>3}/{len(files)}] {total_rows:>9,} rows  ({elapsed:.0f}s)")

    # Build a flat DataFrame of per-body aggregates
    rows = []
    for body in body_counter:
        row = {"body_key": body, "n_docs": body_counter[body]}
        row.update({f"size_{k}": v for k, v in size_acc[body].summary().items()})
        row.update({f"text_{k}": v for k, v in text_len_acc[body].summary().items()})
        rows.append(row)
    docs_stats = pd.DataFrame(rows).sort_values("n_docs", ascending=False).reset_index(drop=True)

    # Long-format tables for the dimensional breakdowns
    docs_formats = pd.DataFrame(
        [{"body_key": b, "format": f, "n": n} for (b, f), n in format_counter.items()]
    )
    docs_langs = pd.DataFrame(
        [{"body_key": b, "language": l, "n": n} for (b, l), n in lang_counter.items()]
    )
    docs_parents = pd.DataFrame(
        [{"body_key": b, "parent_type": p, "n": n} for (b, p), n in parent_counter.items()]
    )
    docs_cats = pd.DataFrame(
        [{"body_key": b, "category_harmonized": c, "n": n} for (b, c), n in cat_counter.items()]
    )

    docs_stats.to_parquet(DOCS_CACHE, index=False)
    docs_formats.to_parquet(EDA_OUT / "docs_formats.parquet", index=False)
    docs_langs.to_parquet(EDA_OUT / "docs_langs.parquet", index=False)
    docs_parents.to_parquet(EDA_OUT / "docs_parents.parquet", index=False)
    docs_cats.to_parquet(EDA_OUT / "docs_categories.parquet", index=False)
    print(f"Scanned {total_rows:,} doc rows across {len(files)} files in {time.perf_counter() - t0:.1f}s")
    print(f"Wrote {DOCS_CACHE.name} + 4 dimensional parquets")

# Always reload the long-format tables (cheap even when main stats are cached)
docs_formats = pd.read_parquet(EDA_OUT / "docs_formats.parquet")
docs_langs = pd.read_parquet(EDA_OUT / "docs_langs.parquet")
docs_parents = pd.read_parquet(EDA_OUT / "docs_parents.parquet")
docs_cats = pd.read_parquet(EDA_OUT / "docs_categories.parquet")
docs_stats.head(10)"""))

CELLS.append(code("""# Top 15 bodies by document count
top = docs_stats.head(15)
fig, ax = plt.subplots(figsize=(11, 5))
ax.barh(top["body_key"], top["n_docs"], color="#2ca02c")
ax.invert_yaxis()
ax.set_xlabel("Documents")
ax.set_title("Top 15 bodies by document count")
for i, v in enumerate(top["n_docs"]):
    ax.text(v, i, f" {int(v):,}", va="center", fontsize=9)
plt.tight_layout()
plt.show()"""))

CELLS.append(code("""# Document formats across the corpus
top_formats = (
    docs_formats.groupby("format")["n"].sum().sort_values(ascending=False).head(10)
)
print("Top 10 document formats:")
print(top_formats.to_string())

fig, ax = plt.subplots(figsize=(10, 4))
ax.barh(top_formats.index, top_formats.values, color="#ff7f0e")
ax.invert_yaxis()
ax.set_xlabel("Documents")
ax.set_title("Top 10 MIME types across all bodies")
plt.tight_layout()
plt.show()"""))

CELLS.append(code("""# Document languages across the corpus
top_langs = (
    docs_langs.groupby("language")["n"].sum().sort_values(ascending=False).head(10)
)
print("Top 10 document languages:")
print(top_langs.to_string())"""))

CELLS.append(code("""# Text-length stats for top bodies (chars of Tika-extracted text)
length_view = docs_stats[["body_key", "n_docs", "text_count", "text_mean", "text_p50", "text_p95"]].head(15).copy()
for c in ["text_count", "text_mean", "text_p50", "text_p95"]:
    length_view[c] = length_view[c].round(0).astype(int)
length_view"""))

# ---------------------------------------------------------------- section 8
CELLS.append(md("""## 8. Full scan — speeches

Stream every `speeches_*.ndjson.gz`. Each row is one speaking turn in a
plenary debate, with `text_content_de/fr/it` translations where
available."""))
CELLS.append(code("""SPEECHES_CACHE = EDA_OUT / "speeches_stats.parquet"
SPEECHES_DIR = EXPORTS_DIR / "speeches"

if USE_CACHE and SPEECHES_CACHE.exists():
    speeches_stats = pd.read_parquet(SPEECHES_CACHE)
    print(f"Loaded from cache: {SPEECHES_CACHE.name} ({len(speeches_stats)} rows)")
else:
    t0 = time.perf_counter()
    accumulators: dict[tuple[str, str], LengthAccumulator] = defaultdict(LengthAccumulator)
    files = sorted(SPEECHES_DIR.glob("speeches_*.ndjson.gz"))
    total_rows = 0
    for fp in files:
        file_rows = 0
        for rec in iter_ndjson_gz(fp):
            body = rec.get("body_key") or "UNKNOWN"
            for lang in ("de", "fr", "it"):
                text = rec.get(f"text_content_{lang}")
                if text and text != "None":
                    n_chars, _ = text_stats(text)
                    if n_chars > 0:
                        accumulators[(body, lang)].add(n_chars)
            file_rows += 1
        total_rows += file_rows
        print(f"  {fp.name}: {file_rows:,} rows")
    rows = []
    for (body, lang), acc in accumulators.items():
        s = acc.summary()
        rows.append({"body_key": body, "language": lang, **s})
    speeches_stats = pd.DataFrame(rows)
    speeches_stats.to_parquet(SPEECHES_CACHE, index=False)
    print(f"Scanned {total_rows:,} speech rows in {time.perf_counter() - t0:.1f}s")

speeches_stats.head()"""))

CELLS.append(code("""per_body_speech = (
    speeches_stats.groupby("body_key")
    .agg(total_speeches=("count", "sum"), mean_chars=("mean", "mean"))
    .sort_values("total_speeches", ascending=False)
)
per_body_speech["mean_chars"] = per_body_speech["mean_chars"].round(0).astype(int)
print("Bodies with speeches in the corpus:")
per_body_speech"""))

# ---------------------------------------------------------------- section 9
CELLS.append(md("""## 9. Full scan — news

Stream every `news_*.ndjson.gz`. News are press releases and similar
announcements published by parliaments and cantonal governments. Schema
is similar to docs (no consistent `text` payload across bodies — we
aggregate counts and language tags only)."""))
CELLS.append(code("""NEWS_CACHE = EDA_OUT / "news_stats.parquet"
NEWS_DIR = EXPORTS_DIR / "news"

if USE_CACHE and NEWS_CACHE.exists():
    news_stats = pd.read_parquet(NEWS_CACHE)
    print(f"Loaded from cache: {NEWS_CACHE.name} ({len(news_stats)} rows)")
else:
    t0 = time.perf_counter()
    # Inspect first row to discover available fields
    first_file = next(NEWS_DIR.glob("news_*.ndjson.gz"))
    sample = next(iter_ndjson_gz(first_file))
    print(f"Sample news keys: {list(sample.keys())}")
    body_counter: Counter[str] = Counter()
    files = sorted(NEWS_DIR.glob("news_*.ndjson.gz"))
    total_rows = 0
    for fp in files:
        for rec in iter_ndjson_gz(fp):
            body = rec.get("body_key") or "UNKNOWN"
            body_counter[body] += 1
            total_rows += 1
    news_stats = (
        pd.DataFrame([{"body_key": b, "n_news": n} for b, n in body_counter.items()])
        .sort_values("n_news", ascending=False)
        .reset_index(drop=True)
    )
    news_stats.to_parquet(NEWS_CACHE, index=False)
    print(f"Scanned {total_rows:,} news rows in {time.perf_counter() - t0:.1f}s")

print(f"Bodies with news: {len(news_stats)}")
news_stats.head(10)"""))

# ---------------------------------------------------------------- section 10
CELLS.append(md("""## 10. Subject areas — labelled subset

The HackApertus challenge provides labels for a subset of parliaments.
Each parliament uses its **own** scheme — these are NOT harmonized:

- **CHE (federal)** — Curia Vista: 28 subject areas (multi-label,
  ~2 per affair) + fine-grained descriptors (German-only, 1996–2014)
- **SG (St. Gallen)** — 10 subject areas, one per affair
- **TG (Thurgau)** — 118 subject areas with systematic codes
- **1711 (Stadt Zug)** — 37 departments (administrative units)
- **ZH (Zürich)** — 724 free keywords (consultations only)

We load each and show its distribution."""))
CELLS.append(code("""# CHE: Curia Vista subject areas
che_vocab = pd.read_csv(HACK_DIR / "che_topics_vocabulary.csv")
print(f"CHE vocabulary: {len(che_vocab)} subject areas")
print(che_vocab.columns.tolist())
che_vocab"""))

CELLS.append(code("""che_kw = pd.read_csv(HACK_DIR / "che_affairs_keywords.csv")
print(f"CHE labelled affairs: {len(che_kw):,}")
print(f"Columns: {che_kw.columns.tolist()}")
che_kw.head(3)"""))

CELLS.append(code("""# Distribution of subject-area IDs (multi-valued, |-separated)
topic_lists = che_kw["topic_ids"].dropna().astype(str).str.split(r"\\s*\\|\\s*")
topic_counts = Counter()
for lst in topic_lists:
    for tid in lst:
        if tid and tid != "None":
            topic_counts[tid.strip()] += 1

# Map ID -> German name via the vocabulary
vocab_lookup = dict(zip(che_vocab["topic_id"].astype(str), che_vocab["topic_de"]))
topic_series = pd.Series(topic_counts).sort_values(ascending=False)
topic_series.index = topic_series.index.map(lambda tid: f"{vocab_lookup.get(tid, tid)} [{tid}]")

fig, ax = plt.subplots(figsize=(11, 6))
topic_series.plot.barh(ax=ax, color="#d62728")
ax.invert_yaxis()
ax.set_xlabel("Affairs (multi-label)")
ax.set_title("CHE — Curia Vista subject areas (all 28)")
for i, v in enumerate(topic_series.values):
    ax.text(v, i, f" {int(v):,}", va="center", fontsize=8)
plt.tight_layout()
plt.show()"""))

CELLS.append(code("""# Cantonal schemes
cant_kw = pd.read_csv(HACK_DIR / "cantonal_affairs_keywords.csv")
cant_vocab = pd.read_csv(HACK_DIR / "cantonal_keywords_vocabulary.csv")
print(f"Cantonal labelled affairs: {len(cant_kw):,}")
print(f"Cantonal vocabulary entries: {len(cant_vocab):,}")
print(f"Bodies: {sorted(cant_kw['body_key'].unique())}")
print(cant_kw.groupby("body_key").size())"""))

CELLS.append(code("""fig, axes = plt.subplots(2, 2, figsize=(13, 8))
for ax, body in zip(axes.flat, ["SG", "TG", "1711", "ZH"]):
    sub = cant_kw[cant_kw["body_key"] == body]
    kws = (
        sub["keywords"].dropna().astype(str).str.split(r"\\s*\\|\\s*")
    )
    counts = Counter()
    for lst in kws:
        for kw in lst:
            if kw and kw != "None":
                counts[kw.strip()] += 1
    top = pd.Series(counts).sort_values(ascending=False).head(10)
    ax.barh(top.index[::-1], top.values[::-1], color="#1f77b4")
    ax.set_title(f"{body} — top 10 keywords ({len(sub):,} affairs)")
    ax.set_xlabel("Affairs")
    ax.tick_params(axis="y", labelsize=8)
plt.tight_layout()
plt.show()"""))

# ---------------------------------------------------------------- section 11
CELLS.append(md("""## 11. DVS use case — digitalisation

The PolitMonitor file contains 3,433 affairs editorially tagged as
"Digitalisierung" across 35 parliaments (mostly 2018–2026). It is our
positive set for the DVS use case. We look at its body/time/language
distribution."""))
CELLS.append(code("""pm = pd.read_csv(HACK_DIR / "politmonitor_digitalisierung.csv")
pm["begin_date"] = pd.to_datetime(pm["begin_date"], errors="coerce")
print(f"PolitMonitor digitalisation affairs: {len(pm):,}")
print(f"Columns: {pm.columns.tolist()}")
print(f"Bodies: {pm['body_key'].nunique()}")
print(f"Year range: {pm['begin_date'].dt.year.min()} -> {pm['begin_date'].dt.year.max()}")
pm.head(3)"""))

CELLS.append(code("""fig, axes = plt.subplots(1, 2, figsize=(13, 4))

# By body (top 12)
by_body = pm["body_key"].value_counts().head(12)
axes[0].barh(by_body.index, by_body.values, color="#9467bd")
axes[0].invert_yaxis()
axes[0].set_title("PolitMonitor digitalisation — top 12 bodies")
axes[0].set_xlabel("Affairs")

# By year
by_year = pm.groupby(pm["begin_date"].dt.year).size()
axes[1].bar(by_year.index, by_year.values, color="#9467bd")
axes[1].set_title("PolitMonitor digitalisation — per year")
axes[1].set_xlabel("Year")
axes[1].set_ylabel("Affairs")
plt.tight_layout()
plt.show()"""))

CELLS.append(code("""# DVS small reference set
dvs = pd.read_csv(HACK_DIR / "dvs_digitalisierung.csv")
print(f"DVS list: {len(dvs)} affairs across {dvs['body_key'].nunique()} bodies")
print(dvs["body_key"].value_counts().to_string())
overlap = pm["openparldata_id"].isin(dvs["openparldata_id"]).sum()
print(f"Overlap DVS ∩ PolitMonitor: {overlap} / {len(dvs)}")"""))

# ---------------------------------------------------------------- section 12
CELLS.append(md("""## 12. Cross-view — subject × affair type (CHE)

For the federal parliament only, how do Curia Vista subject areas
co-occur with harmonized affair types? E.g., are Motions about
"Bildung" as common as Interpellations about "Gesundheit"?"""))
CELLS.append(code("""# Join CHE keywords to affairs to get harmonized type
che_kw_small = che_kw[["openparldata_id", "topic_ids"]].copy()
che_join = che_kw_small.merge(
    affairs[["id", "type_harmonized_en"]],
    left_on="openparldata_id",
    right_on="id",
    how="left",
)
print(f"Joined {len(che_join):,} CHE affairs ({che_join['type_harmonized_en'].notna().sum():,} with harmonized type)")

# Expand multi-label topics
rows = []
for rec in che_join.itertuples(index=False):
    tids = rec.topic_ids
    if pd.isna(tids):
        continue
    for tid in str(tids).split("|"):
        tid = tid.strip()
        if tid and tid != "None":
            rows.append({
                "topic_id": tid,
                "type_harmonized_en": rec.type_harmonized_en,
            })
che_long = pd.DataFrame(rows)
print(f"Expanded to {len(che_long):,} (affair × topic) rows")"""))

CELLS.append(code("""# Top 10 topics × top 8 harmonized types, heatmap
top10_topic_ids = (
    che_long["topic_id"].value_counts().head(10).index.tolist()
)
top8_types = (
    che_long["type_harmonized_en"].value_counts().head(8).index.tolist()
)
mat = (
    che_long[
        che_long["topic_id"].isin(top10_topic_ids)
        & che_long["type_harmonized_en"].isin(top8_types)
    ]
    .groupby(["topic_id", "type_harmonized_en"]).size()
    .unstack(fill_value=0)
)
# Use topic names
mat.index = [f"{vocab_lookup.get(t, t)}" for t in mat.index]

fig, ax = plt.subplots(figsize=(11, 5))
sns.heatmap(
    np.log10(mat + 1),
    annot=mat, fmt=",",
    cmap="mako",
    cbar_kws={"label": "log10(count+1)"},
    ax=ax,
)
ax.set_title("CHE — subject area × harmonized type")
ax.set_xlabel("Harmonized type")
ax.set_ylabel("Subject area")
plt.xticks(rotation=25, ha="right")
plt.tight_layout()
plt.show()"""))

# ---------------------------------------------------------------- section 13
CELLS.append(md("""## 13. APS target scheme

The Année Politique Suisse (APS) scheme is the **zero-shot target** for
the classification service: 8 domains, 22 chapters, 165 topics. We load
it here so the shape of the target is explicit."""))
CELLS.append(code("""aps_path = HACK_DIR / "aps_topics.xlsx"
aps_topics = pd.read_excel(aps_path, sheet_name="Topics")
aps_chapters = pd.read_excel(aps_path, sheet_name="Chapters")
aps_domains = pd.read_excel(aps_path, sheet_name="Domains")
print(f"APS: {len(aps_domains)} domains, {len(aps_chapters)} chapters, {len(aps_topics)} topics")
print(f"Topics columns: {aps_topics.columns.tolist()}")
aps_domains"""))

CELLS.append(code("""# Topics per chapter
topics_per_chapter = (
    aps_topics.groupby(["chapter_de", "domain_de"]).size().rename("n_topics").reset_index()
    .sort_values(["domain_de", "n_topics"], ascending=[True, False])
)
print("Topics per chapter (grouped by domain):")
topics_per_chapter.head(25)"""))

# ---------------------------------------------------------------- final
CELLS.append(md("""## Summary

Print a compact recap of what was computed and where outputs live.
This cell is the canonical record per AGENTS.md §6."""))
CELLS.append(code("""summary = {
    "Affairs loaded (master)": f"{len(affairs):,}",
    "Distinct bodies (affairs)": affairs["body_key"].nunique(),
    "Texts aggregated rows": len(texts_stats),
    "Docs aggregated rows": len(docs_stats),
    "Speeches aggregated rows": len(speeches_stats),
    "News aggregated rows": len(news_stats),
    "CHE labelled affairs": f"{len(che_kw):,}",
    "Cantonal labelled affairs": f"{len(cant_kw):,}",
    "PolitMonitor digitalisation": f"{len(pm):,}",
    "DVS list": len(dvs),
    "APS topics": len(aps_topics),
}
summary_df = pd.Series(summary, name="value").to_frame()
print(summary_df.to_string())
print()
print("Output artefacts under data/eda/:")
for p in sorted(EDA_OUT.glob("*.parquet")):
    size_kb = p.stat().st_size / 1024
    print(f"  {p.name:40s} {size_kb:>10.1f} KB")
print()
print("Next steps: 02_baseline.ipynb — Apertus zero-shot classification on the labelled sample.")
"""))


# ---------------------------------------------------------------- build nb
nb = {
    "cells": CELLS,
    "metadata": {
        "kernelspec": {
            "display_name": "aperTOPic (Python 3.11)",
            "language": "python",
            "name": "aperTOPic",
        },
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out_path = Path("notebooks/01_eda.ipynb")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {out_path} ({len(CELLS)} cells)")
