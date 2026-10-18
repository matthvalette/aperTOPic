"""Loaders for source classification schemes and APS topics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from topic_mapping.prompts import ApsTopic


@dataclass(frozen=True)
class SourceLabel:
    """One label from a source classification scheme."""

    scheme: str  # e.g. "curia_vista_subject_areas", "cantonal_SG", "cantonal_TG", "cantonal_ZH"
    source_id: str  # unique identifier within scheme
    label_de: str
    label_fr: str | None
    label_it: str | None
    affair_count: int
    extra: dict  # any extra provenance


def load_aps_topics(xlsx_path: Path) -> list[ApsTopic]:
    """Load the 165 APS topics from the Excel sheet."""
    df = pd.read_excel(xlsx_path, sheet_name="Topics")
    return [
        ApsTopic(
            code=row["code"],
            domain_de=row["domain_de"],
            domain_fr=row["domain_fr"],
            chapter_de=row["chapter_de"],
            chapter_fr=row["chapter_fr"],
            topic_de=row["topic_de"],
            topic_fr=row["topic_fr"],
        )
        for _, row in df.iterrows()
    ]


def load_curia_vista_labels(vocab_path: Path) -> list[SourceLabel]:
    """Load the 28 federal Curia Vista subject areas."""
    df = pd.read_csv(vocab_path, encoding="utf-8")
    return [
        SourceLabel(
            scheme="curia_vista_subject_areas",
            source_id=str(row["topic_id"]),
            label_de=row["topic_de"],
            label_fr=row["topic_fr"] if pd.notna(row["topic_fr"]) else None,
            label_it=row["topic_it"] if pd.notna(row["topic_it"]) else None,
            affair_count=int(row["affairs"]),
            extra={},
        )
        for _, row in df.iterrows()
    ]


def load_cantonal_labels(
    vocab_path: Path, zh_min_affairs: int = 2
) -> dict[str, list[SourceLabel]]:
    """Load cantonal keywords grouped by body.

    Returns
    -------
    dict
        Keys: ``"SG"``, ``"TG"``, ``"ZH"``. Zug (``1711``) is excluded per
        project decision.
    """
    df = pd.read_csv(vocab_path, encoding="utf-8")
    out: dict[str, list[SourceLabel]] = {"SG": [], "TG": [], "ZH": []}

    for body in ("SG", "TG", "ZH"):
        sub = df[df["body_key"].astype(str) == body]
        if body == "ZH":
            sub = sub[sub["affairs"] >= zh_min_affairs]
        for idx, row in sub.iterrows():
            code = (
                str(row["keyword_code"])
                if pd.notna(row["keyword_code"])
                else f"{body}-{idx}"
            )
            out[body].append(
                SourceLabel(
                    scheme=f"cantonal_{body}",
                    source_id=code,
                    label_de=row["keyword_de"],
                    label_fr=None,
                    label_it=None,
                    affair_count=int(row["affairs"]),
                    extra={"body_key": body},
                )
            )
    return out


def load_sample_titles_per_label(
    affairs_path: Path, body_key: str | None = None, n: int = 5
) -> dict[str, list[str]]:
    """Return up to ``n`` sample affair titles per source label.

    For federal: ``che_affairs_keywords.csv`` keyed by topic name.
    For cantonal: ``cantonal_affairs_keywords.csv`` keyed by body+keyword.
    """
    df = pd.read_csv(affairs_path, encoding="utf-8", low_memory=False)
    samples: dict[str, list[str]] = {}
    if body_key is None:
        # federal: topics_de is " | "-separated
        for _, row in df.iterrows():
            if pd.isna(row.get("topics_de")):
                continue
            for topic in str(row["topics_de"]).split(" | "):
                topic = topic.strip()
                samples.setdefault(topic, [])
                if len(samples[topic]) < n and pd.notna(row.get("title_de")):
                    samples[topic].append(str(row["title_de"]))
    else:
        sub = df[df["body_key"].astype(str) == body_key]
        for _, row in sub.iterrows():
            if pd.isna(row.get("keywords")):
                continue
            for kw in str(row["keywords"]).split(" | "):
                kw = kw.strip()
                samples.setdefault(kw, [])
                if len(samples[kw]) < n and pd.notna(row.get("title_de")):
                    samples[kw].append(str(row["title_de"]))
    return samples
