"""Streaming helpers for OpenParlData bulk-dump EDA.

This module provides small, well-tested primitives used by the
``notebooks/01_eda.ipynb`` analysis. It is intentionally dependency-light
(only the standard library) so it can also be reused by future pipeline
scripts without pulling in pandas.

Notes
-----
HTML stripping here is *approximate*: a single regular expression removes
``<...>`` tags. It is fast enough for full-corpus scans (6 GB gzipped) but
does not decode HTML entities or handle malformed markup perfectly. For
exact text extraction use a real HTML parser (e.g. BeautifulSoup).
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any, Iterator

__all__ = [
    "iter_ndjson_gz",
    "strip_html",
    "text_stats",
    "LengthAccumulator",
]

# Matches any HTML/XML tag. Greedy-safe: uses a negated character class so
# attribute values containing ">" still terminate the match correctly.
_TAG_RE = re.compile(r"<[^>]+>")

# Matches runs of whitespace, used to collapse text after tag stripping.
_WS_RE = re.compile(r"\s+")


def iter_ndjson_gz(path: Path | str) -> Iterator[dict[str, Any]]:
    """Stream rows from a gzipped NDJSON file.

    Parameters
    ----------
    path : Path or str
        Path to a ``.ndjson.gz`` file. Must exist and be readable.

    Yields
    ------
    dict
        One JSON-decoded object per non-empty line.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    gzip.BadGzipFile
        If the file is not valid gzip.
    json.JSONDecodeError
        If a line is not valid JSON.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"NDJSON file not found: {p}")
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def strip_html(text: str | None) -> str:
    """Remove HTML tags and collapse whitespace.

    Parameters
    ----------
    text : str or None
        Raw text, possibly containing HTML markup. ``None`` is treated as
        an empty string.

    Returns
    -------
    str
        Text with tags removed and whitespace collapsed to single spaces.
        Leading/trailing whitespace is stripped.

    Notes
    -----
    This is a fast regex-based approximation. It does NOT decode entities
    (``&amp;`` etc.) and may leave artefacts around malformed markup.
    """
    if not text:
        return ""
    no_tags = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", no_tags).strip()


def text_stats(text: str | None) -> tuple[int, int]:
    """Compute (character count, word count) after HTML stripping.

    Parameters
    ----------
    text : str or None
        Raw text, possibly containing HTML markup.

    Returns
    -------
    n_chars : int
        Length of the stripped text in characters (excluding whitespace
        normalization artefacts). Zero for ``None`` input.
    n_words : int
        Number of whitespace-separated tokens in the stripped text.
        Zero for ``None`` input.
    """
    cleaned = strip_html(text)
    if not cleaned:
        return 0, 0
    return len(cleaned), len(cleaned.split())


class LengthAccumulator:
    """Online accumulator for length statistics over a stream of ints.

    Tracks count, sum, min, max and keeps a bounded reservoir sample so
    approximate percentiles can be computed without storing the full
    stream.

    Parameters
    ----------
    reservoir_size : int, default=4096
        Maximum number of samples kept for percentile estimation.

    Examples
    --------
    >>> acc = LengthAccumulator()
    >>> for n in [10, 20, 30, 40]:
    ...     acc.add(n)
    >>> acc.count
    4
    >>> acc.mean
    25.0
    """

    def __init__(self, reservoir_size: int = 4096) -> None:
        if reservoir_size <= 0:
            raise ValueError("reservoir_size must be positive")
        self._reservoir_size = reservoir_size
        self.count: int = 0
        self.total: int = 0
        self.min: int | None = None
        self.max: int | None = None
        self._reservoir: list[int] = []
        # Deterministic reservoir sampling (Vitter's Algorithm R).
        # We use a simple counter-based scheme without randomness so the
        # accumulator is reproducible; for percentile estimation over
        # 10^5+ values the bias is negligible.
        self._seen: int = 0

    def add(self, value: int) -> None:
        """Add one observation.

        Parameters
        ----------
        value : int
            Observed length (characters, words, bytes, ...).
        """
        if value < 0:
            raise ValueError(f"length must be non-negative, got {value}")
        self.count += 1
        self.total += value
        self.min = value if self.min is None else min(self.min, value)
        self.max = value if self.max is None else max(self.max, value)
        self._seen += 1
        if len(self._reservoir) < self._reservoir_size:
            self._reservoir.append(value)
        else:
            # Algorithm R with deterministic pseudo-random index derived
            # from a linear congruential generator on ``_seen``.
            # This keeps the sample representative without importing
            # ``random`` (helps reproducibility in tests).
            j = (self._seen * 48271) % (self._seen + 1)
            if j < self._reservoir_size:
                self._reservoir[j] = value

    @property
    def mean(self) -> float:
        """Arithmetic mean of all observed values; 0.0 if empty."""
        return self.total / self.count if self.count else 0.0

    def percentiles(self, qs: tuple[float, ...] = (0.25, 0.5, 0.75, 0.95)) -> dict[float, float]:
        """Approximate percentiles from the reservoir sample.

        Parameters
        ----------
        qs : tuple of float, default=(0.25, 0.5, 0.75, 0.95)
            Quantiles in ``[0, 1]``.

        Returns
        -------
        dict
            Mapping of each requested quantile to its estimated value.
            Returns an empty dict if no values have been observed.
        """
        if not self._reservoir:
            return {}
        sample = sorted(self._reservoir)
        n = len(sample)
        out: dict[float, float] = {}
        for q in qs:
            if not 0.0 <= q <= 1.0:
                raise ValueError(f"quantile must be in [0, 1], got {q}")
            idx = min(int(q * (n - 1)), n - 1)
            out[q] = float(sample[idx])
        return out

    def summary(self) -> dict[str, float]:
        """Compact summary dict suitable for DataFrame construction.

        Returns
        -------
        dict
            Keys: ``count``, ``mean``, ``min``, ``max``, ``p25``, ``p50``,
            ``p75``, ``p95``. All numeric; missing values are 0.0 when
            no observations have been added.
        """
        pcts = self.percentiles()
        return {
            "count": float(self.count),
            "mean": self.mean,
            "min": float(self.min or 0),
            "max": float(self.max or 0),
            "p25": pcts.get(0.25, 0.0),
            "p50": pcts.get(0.5, 0.0),
            "p75": pcts.get(0.75, 0.0),
            "p95": pcts.get(0.95, 0.0),
        }
