"""Apertus through an OpenAI-compatible chat API (the Keera gateway by default).

Implements `QueryTranslator`: one free-text request in, short title-style search queries
per parliament language out.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

import httpx

from ..domain.models import QueryVariants

log = logging.getLogger(__name__)

LANGUAGE_NAMES = {
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "rm": "Romansh",
    "en": "English",
}

SYSTEM_PROMPT = """You write search queries for a database of Swiss parliamentary affairs \
(motions, postulates, interpellations, questions, bills) from the federal, cantonal and \
municipal parliaments. The search matches words in affair titles, and every word of a query \
must appear in a title for it to match.

Given a search request in any language, write search queries in each requested language:
- Give up to {n} different queries per language.
- Each query has 1 to 3 words: only the essential nouns and adjectives, no articles or \
prepositions. Use the official terminology and common abbreviations a parliamentary title in \
that language would use (for example KI, IA, IV, AHV, AVS).
- The first query is the most direct translation of the request. The others use synonyms or \
closely related official terms.
- No quotes, operators, explanations or duplicate queries.

Example. Request: "noise from airports". Answer:
{{"de": ["Fluglärm", "Lärm Flughafen", "Lärmschutz Luftverkehr"], \
"fr": ["bruit aéroport", "nuisances sonores aviation"], \
"it": ["rumore aeroporto", "inquinamento fonico aereo"], "rm": ["canera aviun"]}}

Return only a JSON object that maps each language code to a list of queries."""

_JSON_OBJECT = re.compile(r"\{.*\}", re.S)
_STRIP = re.compile(r"[\"«»“”„`*]")  # quotation marks, not apostrophes (l'IA, dell'IA)


def parse_variants(
    content: str, languages: Sequence[str], n: int, fallback: str
) -> list[QueryVariants]:
    """Parse the model's JSON answer. Every requested language gets at least the fallback query."""
    data: dict[str, Any] = {}
    match = _JSON_OBJECT.search(content or "")
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            log.warning("Apertus returned invalid JSON: %.200s", content)
    result: list[QueryVariants] = []
    for lang in languages:
        raw = data.get(lang)
        items = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
        queries: list[str] = []
        for item in items:
            if not isinstance(item, str):
                continue
            query = " ".join(_STRIP.sub(" ", item).split()).strip("'‘’ ")
            if query and query.lower() not in {q.lower() for q in queries}:
                queries.append(query)
        result.append(QueryVariants(language=lang, queries=queries[:n] or [fallback]))
    return result


class ApertusQueryTranslator:
    def __init__(self, http: httpx.AsyncClient, *, base_url: str, api_key: str, model: str) -> None:
        self._http = http
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.model = model

    async def complete(self, system: str, user: str, *, max_tokens: int = 500) -> str:
        response = await self._http.post(
            self._url,
            headers=self._headers,
            json={
                "model": self.model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or ""

    async def translate(
        self, request: str, languages: Sequence[str], variants_per_language: int = 3
    ) -> list[QueryVariants]:
        wanted = ", ".join(f"{code} ({LANGUAGE_NAMES.get(code, code)})" for code in languages)
        content = await self.complete(
            SYSTEM_PROMPT.format(n=variants_per_language),
            f"Languages: {wanted}\nSearch request: {request}",
        )
        return parse_variants(content, languages, variants_per_language, fallback=request)
