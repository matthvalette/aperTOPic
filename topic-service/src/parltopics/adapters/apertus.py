"""Apertus through an OpenAI-compatible chat API (the Keera gateway by default).

Implements `QueryTranslator`: one free-text request in, short title-style search queries
per parliament language out.

Implements `KeywordWriter`: one document in, the words titles of affairs on the same subject
contain, per parliament language out (used to find similar cases).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from ..domain.models import DocumentKeywords, QueryVariants, SourceDocument
from .jev import SECTION_ORDER

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

_STRIP = re.compile(r"[\"«»“”„`*]")  # quotation marks, not apostrophes (l'IA, dell'IA)


def first_json_object(content: str) -> dict[str, Any]:
    """The first complete JSON object in the answer. Apertus often adds a stray closing brace after it,
    which a greedy first-to-last-brace match turns into invalid JSON."""
    decoder = json.JSONDecoder()
    start = (content or "").find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(content, start)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        start = content.find("{", start + 1)
    if content and "{" in content:
        log.warning("Apertus returned invalid JSON: %.200s", content)
    return {}


def parse_variants(
    content: str, languages: Sequence[str], n: int, fallback: str
) -> list[QueryVariants]:
    """Parse the model's JSON answer. Every requested language gets at least the fallback query."""
    data = first_json_object(content)
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


# ---------- KeywordWriter: words for finding similar cases ----------

# Chosen on 42 documents (20 dev, 22 held-out test) against six alternatives, including writing
# whole queries and summarising the document for the /search translator. Single title words win
# because the search needs every query word in a title: the service combines them by hit count.
KEYWORDS_PROMPT = """You help find other parliamentary affairs on the same subject as a given affair, in a database \
of Swiss federal, cantonal and municipal affairs. The search looks for words in affair titles only. A title matches \
a word only if it contains that word itself (singular and plural are the same word, but Bauten is not Bauen, and \
part of a compound does not count).

Read the affair. Then, for each requested language, list up to {k} words that titles of affairs on the same \
specific subject contain, in this order:
1. The one or two words that name the subject itself, in the form titles use most (Afghaninnen, Herdenschutz, \
Spitalplanung, cabotage, LAMal).
2. Other forms and synonyms of the subject that titles also use: the short base word next to the compound \
(Afghanistan next to Afghaninnen, Westast next to Westumfahrung, Bauzone next to Bauzonen), common abbreviations, \
other official terms (Jugendpsychiatrie next to psychische Gesundheit).
3. Words that narrow the subject down (the object, the group concerned, the place of a specific named project).
Rules:
- One word per entry. Two words only for a fixed term written as two words (Service public, intelligence \
artificielle, ausserhalb Bauzone). No hyphenated combinations a title would not use.
- No procedural or generic words (motion, question, rapport, Bericht, Kanton, canton, Bund, Gesetz, loi, \
Massnahmen, mesures, Analyse, situation) and no names of persons, parties, cantons or municipalities, unless the \
affair is about one specific named object such as a road, an airport or a building.
- Use the terms each language's parliaments actually use (official terminology), not word-for-word translations.
- Romansh: only words you are sure of. An empty list is fine.

Answer with a JSON object: {{"subject": "<the specific subject, one short English sentence>", "keywords": \
{{"de": [...], "fr": [...], "it": [...], "rm": [...]}}}}

Example. Affair: "Interpellation: Wolfsrisse auf Alpweiden. Der Regierungsrat wird gefragt, wie er die Schafhalter \
beim Herdenschutz unterstützt ..." Answer:
{{"subject": "Wolf attacks on livestock and herd protection.", "keywords": {{"de": ["Wolf", "Herdenschutz", \
"Wolfsrisse", "Wölfe", "Herdenschutzhunde", "Grossraubtiere", "Schafe", "Alpwirtschaft"], "fr": ["loup", \
"protection des troupeaux", "loups", "grands prédateurs", "attaques", "moutons", "alpage"], "it": ["lupo", \
"protezione delle greggi", "lupi", "grandi predatori", "predazioni", "pecore", "alpeggi"], "rm": ["luf", "lufs"]}}}}"""

KEYWORDS_PER_LANGUAGE = 8
PROMPT_SECTION_NAMES = {
    "title": "Title",
    "lead": "Summary",
    "submitted_text": "Submitted text",
    "reasoning": "Reasoning",
    "answer": "Answer",
    "document": "Document",
}


def _base_section(name: str) -> str:
    """document_2 -> document; other section names unchanged."""
    return re.sub(r"_\d+$", "", name)


def document_prompt_text(
    document: SourceDocument,
    parliaments: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    max_chars: int = 3500,
    max_section: int = 2000,
) -> str:
    """The document as short plain text: parliament, type, title, then the sections, repeats removed."""
    lines = []
    if document.body_key:
        name = ((parliaments or {}).get(document.body_key) or {}).get("name")
        lines.append(f"Parliament: {name} ({document.body_key})" if name else f"Parliament: {document.body_key}")
    if document.affair_type:
        lines.append(f"Type: {document.affair_type}")
    title = document.sections.get("title") or document.title
    if title:
        lines.append(f"Title: {title}")
    order = {name: index for index, name in enumerate(SECTION_ORDER)}
    sections = sorted(
        ((name, text) for name, text in document.sections.items() if name != "title" and text),
        key=lambda item: order.get(_base_section(item[0]), len(order)),
    )
    budget = max_chars - sum(len(line) for line in lines)
    seen: set[str] = set()
    for name, text in sections:
        fingerprint = text[:300]  # attachments are often the same PDF twice
        if fingerprint in seen or budget <= 200:
            continue
        seen.add(fingerprint)
        piece = " ".join(text.split())[: min(max_section, budget)]
        lines.append(f"{PROMPT_SECTION_NAMES.get(_base_section(name), name)}: {piece}")
        budget -= len(piece)
    return "\n".join(lines)


def _clean_word(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    word = " ".join(_STRIP.sub(" ", value).split()).strip("'‘’ .,;:")
    return word or None


def parse_keywords(content: str, languages: Sequence[str]) -> DocumentKeywords:
    """Parse the model's JSON answer. Missing or broken languages get an empty list."""
    data = first_json_object(content)
    raw = data.get("keywords") if isinstance(data.get("keywords"), dict) else {}
    words: dict[str, list[str]] = {}
    for lang in languages:
        items = raw.get(lang)
        items = [items] if isinstance(items, str) else items if isinstance(items, list) else []
        cleaned: list[str] = []
        for item in items:
            word = _clean_word(item)
            if word and word.lower() not in {w.lower() for w in cleaned}:
                cleaned.append(word)
        words[lang] = cleaned
    subject = data.get("subject")
    return DocumentKeywords(subject=subject.strip() if isinstance(subject, str) and subject.strip() else None, words=words)


class ApertusKeywordWriter:
    """The words titles of affairs on a document's subject contain, per language. One chat call."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        parliaments: Mapping[str, Mapping[str, Any]] | None = None,
        words_per_language: int = KEYWORDS_PER_LANGUAGE,
    ) -> None:
        self._http = http
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.model = model
        self._parliaments = parliaments or {}
        self._words = words_per_language

    async def keywords(self, document: SourceDocument, languages: Sequence[str]) -> DocumentKeywords:
        wanted = ", ".join(f"{code} ({LANGUAGE_NAMES.get(code, code)})" for code in languages)
        response = await self._http.post(
            self._url,
            headers=self._headers,
            json={
                "model": self.model,
                "temperature": 0,
                "max_tokens": 700,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": KEYWORDS_PROMPT.format(k=self._words)},
                    {
                        "role": "user",
                        "content": f"Languages: {wanted}\nAffair:\n{document_prompt_text(document, self._parliaments)}",
                    },
                ],
            },
        )
        response.raise_for_status()
        return parse_keywords(response.json()["choices"][0]["message"]["content"] or "", languages)
