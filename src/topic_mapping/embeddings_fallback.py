"""Embedding-based fallback when Apertus is unavailable.

Uses sentence-transformers multilingual-mpnet for DE/FR/IT similarity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from topic_mapping.classify import MappingResult
from topic_mapping.data_loaders import SourceLabel
from topic_mapping.prompts import ApsTopic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "paraphrase-multilingual-mpnet-base-v2"
DEFAULT_TOP_K_PRIMARY = 3
DEFAULT_TOP_K_SECONDARY = 8
DEFAULT_SECONDARY_RATIO = 0.85  # secondary if sim >= primary_sim * ratio


@dataclass
class EmbeddingConfig:
    """Configuration for the embedding fallback."""

    model_name: str = DEFAULT_MODEL
    top_k_primary: int = DEFAULT_TOP_K_PRIMARY
    top_k_secondary: int = DEFAULT_TOP_K_SECONDARY
    secondary_ratio: float = DEFAULT_SECONDARY_RATIO


_model_cache: dict = {}


def _get_model(model_name: str):
    """Lazy-load and cache the sentence-transformers model."""
    if model_name not in _model_cache:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model %s (first call)...", model_name)
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def _source_text(source: SourceLabel) -> str:
    parts = [source.label_de]
    if source.label_fr:
        parts.append(source.label_fr)
    if source.label_it:
        parts.append(source.label_it)
    return " | ".join(parts)


def _aps_text(topic: ApsTopic) -> str:
    return (
        f"{topic.domain_de} > {topic.chapter_de} > {topic.topic_de} | "
        f"{topic.domain_fr} > {topic.chapter_fr} > {topic.topic_fr}"
    )


def map_label_with_embeddings(
    source: SourceLabel,
    aps_topics: list[ApsTopic],
    config: EmbeddingConfig | None = None,
) -> MappingResult:
    """Map a source label via cosine similarity on multilingual embeddings."""
    cfg = config or EmbeddingConfig()
    model = _get_model(cfg.model_name)

    src_emb = model.encode(_source_text(source), normalize_embeddings=True)
    aps_texts = [_aps_text(t) for t in aps_topics]
    aps_embs = model.encode(aps_texts, normalize_embeddings=True)

    sims = np.dot(aps_embs, src_emb)
    ranked_idx = np.argsort(-sims)

    primary_idx = ranked_idx[: cfg.top_k_primary]
    primary_sims = sims[primary_idx]
    primary_cutoff = float(primary_sims.min())

    secondary_idx = [
        i
        for i in ranked_idx[cfg.top_k_primary :]
        if sims[i] >= primary_cutoff * cfg.secondary_ratio
    ][: cfg.top_k_secondary]

    primary_codes = [aps_topics[i].code for i in primary_idx]
    secondary_codes = [aps_topics[i].code for i in secondary_idx]

    return MappingResult(
        source=source,
        primary_codes=primary_codes,
        secondary_codes=secondary_codes,
        method=f"embeddings:{cfg.model_name}",
    )
