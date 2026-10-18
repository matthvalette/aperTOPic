"""HTTP client for the Apertus LLM endpoint.

Handles authentication, retries, JSON-mode parsing, and error logging.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 120
MAX_RETRIES = 3
RETRY_BACKOFF_S = 2.0


@dataclass
class ApertusResponse:
    """Parsed response from the Apertus endpoint."""

    content: str
    raw: dict[str, Any]
    latency_s: float
    content_hash: str


class ApertusError(Exception):
    """Raised when the Apertus endpoint returns an unusable response."""


class ApertusClient:
    """Thin wrapper around an OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ) -> None:
        """Initialise the client.

        Parameters
        ----------
        base_url
            Endpoint base URL. Falls back to ``LLM_BASE_URL`` env var.
        api_key
            API key. Falls back to ``LLM_API_KEY`` env var.
        model
            Model identifier. Falls back to ``LLM_NAME`` env var.
        timeout_s
            Request timeout in seconds.

        Raises
        ------
        ApertusError
            If any required configuration value is missing.
        """
        load_dotenv(Path.cwd() / ".env")
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or ""
        self.model = model or os.environ.get("LLM_NAME") or ""
        self.timeout_s = timeout_s

        missing = [
            name
            for name, value in (
                ("LLM_BASE_URL", self.base_url),
                ("LLM_API_KEY", self.api_key),
                ("LLM_NAME", self.model),
            )
            if not value
        ]
        if missing:
            raise ApertusError(
                f"Missing required configuration: {', '.join(missing)}. "
                "Set env vars or pass explicitly."
            )

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> ApertusResponse:
        """Send a chat completion request with retry/backoff.

        Parameters
        ----------
        messages
            Chat messages in OpenAI format.
        temperature
            Sampling temperature. Default 0 for deterministic output.
        max_tokens
            Maximum tokens to generate.
        response_format
            Optional JSON-mode hint, e.g. ``{"type": "json_object"}``.

        Returns
        -------
        ApertusResponse
            Parsed content and metadata.

        Raises
        ------
        ApertusError
            After exhausting retries on non-200 or malformed responses.
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            started = time.monotonic()
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_s,
                )
                latency = time.monotonic() - started
                if resp.status_code != 200:
                    raise ApertusError(
                        f"Apertus HTTP {resp.status_code} "
                        f"(payload {len(json.dumps(payload))} B): "
                        f"{resp.text[:500]}"
                    )
                body = resp.json()
                content = (
                    body.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                if not content:
                    raise ApertusError(f"Empty content in response: {body}")
                return ApertusResponse(
                    content=content,
                    raw=body,
                    latency_s=latency,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            except (requests.RequestException, ApertusError) as exc:
                last_error = exc
                logger.warning(
                    "Apertus attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_S * attempt)

        raise ApertusError(
            f"Apertus request failed after {MAX_RETRIES} attempts: {last_error}"
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], ApertusResponse]:
        """Chat completion expecting a JSON response.

        Returns
        -------
        tuple
            ``(parsed_json, raw_response)``.

        Raises
        ------
        ApertusError
            If the response cannot be parsed as JSON after retries.
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        # Strip markdown code fences if present (some models wrap JSON in ```).
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ApertusError(
                f"Failed to parse JSON from Apertus response: {exc}. "
                f"Content preview: {content[:500]}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ApertusError(f"Expected JSON object, got {type(parsed).__name__}")
        return parsed, response
