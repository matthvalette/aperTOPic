"""OpenParlData REST API (api.openparldata.ch): search, affairs, texts and documents.

Implements `AffairSearchEngine` and `AffairRepository`.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from ..domain.models import AffairSummary, DocumentText, TextBlock

SUMMARY_FIELDS = "id,body_key,number,title,type_harmonized,begin_date,url_external"

# Federal text types (Curia Vista) mapped to stable section names.
TEXT_KINDS = {
    "Titel des Geschäftes": "title",
    "Eingereichter Text": "submitted_text",
    "Begründung": "reasoning",
    "Antwort BR / Büro": "answer",
    "Lead": "lead",
}

ALLOWED_FILE_HOSTS = {"files.openparldata.ch"}

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def clean_text(value: str | None) -> str:
    """Strip HTML markup and collapse whitespace. Texts carry HTML even when marked as text."""
    if not value:
        return ""
    text = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", value, flags=re.I)
    text = html.unescape(_TAG.sub(" ", text))
    text = _SPACE.sub(" ", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _localized(value: Any) -> dict[str, str]:
    """A per-language field; titles sometimes carry HTML entities such as &amp;."""
    if isinstance(value, dict):
        return {k: html.unescape(v) for k, v in value.items() if isinstance(v, str) and v}
    return {}


class OpenParlDataError(RuntimeError):
    pass


class OpenParlDataClient:
    def __init__(self, http: httpx.AsyncClient, *, base_url: str, site_url: str) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._site = site_url.rstrip("/")

    # ---------- helpers ----------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._http.get(f"{self._base}{path}", params=params)
        if response.status_code == 404:
            raise LookupError(f"OpenParlData has no {path}")
        if response.status_code >= 400:
            raise OpenParlDataError(f"OpenParlData {path} returned {response.status_code}: {response.text[:300]}")
        return response.json()

    def site_url(self, category: str, item_id: int) -> str:
        return f"{self._site}/item/{category}/{item_id}"

    def _summary(self, row: dict[str, Any]) -> AffairSummary:
        affair_id = int(row["id"])
        return AffairSummary(
            id=affair_id,
            body_key=str(row.get("body_key") or ""),
            number=row.get("number"),
            title=_localized(row.get("title")),
            type=_localized(row.get("type_harmonized")),
            begin_date=_parse_date(row.get("begin_date")),
            url=self.site_url("affairs", affair_id),
            url_api=f"{self._base}/affairs/{affair_id}",
            url_external=_localized(row.get("url_external")),
        )

    @staticmethod
    def _doc(row: dict[str, Any]) -> DocumentText:
        return DocumentText(
            id=int(row["id"]) if row.get("id") is not None else None,
            name=row.get("name"),
            url=row.get("url_oparl") or row.get("url"),
            format=row.get("format"),
            affair_id=int(row["affair_id"]) if row.get("affair_id") else None,
            text=clean_text(row.get("text")),
        )

    # ---------- AffairSearchEngine ----------

    async def search_affairs(
        self,
        query: str,
        *,
        language: str,
        scope: str = "metadata",
        mode: str = "natural",
        limit: int = 20,
        body_keys: Sequence[str] = (),
    ) -> list[AffairSummary]:
        params: dict[str, Any] = {
            "search": query,
            "search_mode": mode,
            "search_language": language,
            "search_scope": scope,
            "limit": limit,
            "fields": SUMMARY_FIELDS,
            "sort_by": "-begin_date",
        }
        if body_keys:
            params["body_key"] = ",".join(body_keys)
        payload = await self._get("/affairs/", params)
        return [self._summary(row) for row in payload.get("data", [])]

    # ---------- AffairRepository ----------

    async def get_affair(self, affair_id: int) -> AffairSummary:
        return self._summary(await self._get(f"/affairs/{affair_id}"))

    async def find_affair(
        self, *, body_key: str, external_id: str | None = None, number: str | None = None
    ) -> AffairSummary | None:
        params: dict[str, Any] = {"body_key": body_key, "limit": 1, "fields": SUMMARY_FIELDS}
        if external_id:
            params["external_id"] = external_id
        elif number:
            params["number"] = number
        else:
            raise ValueError("find_affair needs external_id or number")
        rows = (await self._get("/affairs/", params)).get("data", [])
        return self._summary(rows[0]) if rows else None

    async def get_texts(self, affair_id: int) -> list[TextBlock]:
        payload = await self._get(f"/affairs/{affair_id}/texts", {"limit": 50})
        blocks: list[TextBlock] = []
        for row in payload.get("data", []):
            kind_names = _localized(row.get("type"))
            raw_kind = kind_names.get("de") or next(iter(kind_names.values()), "text")
            kind = TEXT_KINDS.get(raw_kind, raw_kind)
            for language, text in _localized(row.get("text")).items():
                cleaned = clean_text(text)
                if cleaned:
                    blocks.append(TextBlock(kind=kind, language=language, text=cleaned))
        return blocks

    async def get_docs(self, affair_id: int, limit: int = 5) -> list[DocumentText]:
        payload = await self._get(f"/affairs/{affair_id}/docs", {"limit": limit})
        return [self._doc(row) for row in payload.get("data", [])]

    async def get_doc(self, doc_id: int) -> DocumentText:
        return self._doc(await self._get(f"/docs/{doc_id}"))

    async def download_file(self, url: str, max_bytes: int = 25_000_000) -> tuple[bytes, str | None]:
        host = urlparse(url).hostname or ""
        if host not in ALLOWED_FILE_HOSTS:
            raise ValueError(f"Only files from {', '.join(sorted(ALLOWED_FILE_HOSTS))} can be fetched")
        chunks: list[bytes] = []
        size = 0
        async with self._http.stream("GET", url, follow_redirects=True) as response:
            if response.status_code >= 400:
                raise LookupError(f"{url} returned {response.status_code}")
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"File is larger than {max_bytes // 1_000_000} MB")
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("content-type")
