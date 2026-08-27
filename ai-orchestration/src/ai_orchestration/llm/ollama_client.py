"""Thin HTTP client for a local Ollama server. No cloud API, no SDK dependency - Ollama exposes a
plain REST API (http://localhost:11434 by default) that this talks to directly via `requests`.
"""
from __future__ import annotations

import logging

import requests

from .. import config

log = logging.getLogger("ai_orchestration.llm.ollama_client")


class OllamaUnavailableError(RuntimeError):
    """Raised by `generate()` when the Ollama server can't be reached or times out. Callers (see
    interpret.py) are expected to catch this and degrade gracefully, never propagate it as a
    pipeline failure."""


class OllamaClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, timeout_seconds: float | None = None):
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or config.OLLAMA_MODEL
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else config.OLLAMA_TIMEOUT_SECONDS

    def is_available(self) -> bool:
        """Cheap health check: GET /api/tags. Short, fixed timeout independent of
        `timeout_seconds` (generation timeout) - availability checks should fail fast."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def has_model(self) -> bool:
        """Whether `self.model` is actually pulled (distinct from the server just being up)."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            resp.raise_for_status()
            names = {m.get("name") for m in resp.json().get("models", [])}
            return self.model in names
        except requests.exceptions.RequestException:
            return False

    def generate(self, prompt: str, expect_json: bool = True) -> str:
        """Returns the raw text response. Raises OllamaUnavailableError on any connection error
        or timeout - never returns a fabricated/default response on failure."""
        payload: dict = {"model": self.model, "prompt": prompt, "stream": False}
        if expect_json:
            payload["format"] = "json"

        try:
            resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise OllamaUnavailableError(f"Ollama request timed out after {self.timeout_seconds}s") from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaUnavailableError(f"Ollama request failed: {exc}") from exc

        body = resp.json()
        response_text = body.get("response")
        if response_text is None:
            raise OllamaUnavailableError("Ollama response missing 'response' field")
        return response_text
