"""Category 9: Ollama unavailable handling (plus availability/generate happy paths)."""
from __future__ import annotations

import json

import pytest
import requests
import responses

from ai_orchestration.llm.ollama_client import OllamaClient, OllamaUnavailableError


def _client():
    return OllamaClient(base_url="http://localhost:11434", model="llama3.2:1b", timeout_seconds=5)


@responses.activate
def test_is_available_true_when_server_responds():
    responses.add(responses.GET, "http://localhost:11434/api/tags", json={"models": []}, status=200)

    assert _client().is_available() is True


@responses.activate
def test_is_available_false_when_connection_refused():
    responses.add(responses.GET, "http://localhost:11434/api/tags", body=requests.exceptions.ConnectionError("refused"))

    assert _client().is_available() is False


def test_is_available_false_when_nothing_registered_to_intercept():
    # No `responses.activate` - any real network call would fail/hang; OllamaClient must catch it.
    client = OllamaClient(base_url="http://localhost:1", timeout_seconds=1)
    assert client.is_available() is False


@responses.activate
def test_has_model_true_when_model_name_present():
    responses.add(responses.GET, "http://localhost:11434/api/tags",
                   json={"models": [{"name": "llama3.2:1b"}, {"name": "other:1b"}]}, status=200)

    assert _client().has_model() is True


@responses.activate
def test_has_model_false_when_model_name_absent():
    responses.add(responses.GET, "http://localhost:11434/api/tags", json={"models": [{"name": "other:1b"}]}, status=200)

    assert _client().has_model() is False


@responses.activate
def test_generate_returns_response_text_on_success():
    responses.add(responses.POST, "http://localhost:11434/api/generate",
                   json={"response": json.dumps({"a": 1}), "done": True}, status=200)

    result = _client().generate("some prompt")

    assert json.loads(result) == {"a": 1}


@responses.activate
def test_generate_sends_json_format_when_expect_json_true():
    responses.add(responses.POST, "http://localhost:11434/api/generate", json={"response": "{}"}, status=200)

    _client().generate("prompt", expect_json=True)

    sent_body = json.loads(responses.calls[0].request.body)
    assert sent_body["format"] == "json"
    assert sent_body["stream"] is False


@responses.activate
def test_generate_raises_unavailable_on_timeout():
    responses.add(responses.POST, "http://localhost:11434/api/generate", body=requests.exceptions.Timeout())

    with pytest.raises(OllamaUnavailableError):
        _client().generate("prompt")


@responses.activate
def test_generate_raises_unavailable_on_connection_error():
    responses.add(responses.POST, "http://localhost:11434/api/generate", body=requests.exceptions.ConnectionError())

    with pytest.raises(OllamaUnavailableError):
        _client().generate("prompt")


@responses.activate
def test_generate_raises_unavailable_on_http_error_status():
    responses.add(responses.POST, "http://localhost:11434/api/generate", json={"error": "model not found"}, status=404)

    with pytest.raises(OllamaUnavailableError):
        _client().generate("prompt")
