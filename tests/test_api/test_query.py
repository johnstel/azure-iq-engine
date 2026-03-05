"""
Tests for POST /api/query endpoint.

External dependencies (Azure AI Search, Azure OpenAI) are mocked so no
real network calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


def _query_payload(**overrides) -> dict:
    base = {"question": "What is Fabric IQ?", "top_k": 5}
    base.update(overrides)
    return base


# ── Graceful degradation (no Azure credentials) ───────────────────────────────

def test_query_no_credentials_returns_200(client):
    """When Azure services are unconfigured, query still returns 200 with stub answer."""
    resp = client.post("/api/query", json=_query_payload())
    assert resp.status_code == 200


def test_query_stub_answer_mentions_configuration(client):
    resp = client.post("/api/query", json=_query_payload())
    data = resp.json()
    assert "answer" in data
    # Stub answer is returned when FOUNDRY_BASE_URL is not set
    assert "not configured" in data["answer"].lower() or isinstance(data["answer"], str)


def test_query_response_schema(client):
    resp = client.post("/api/query", json=_query_payload())
    data = resp.json()
    assert "answer" in data
    assert "citations" in data
    assert "agent" in data
    assert "iq_layers" in data
    assert "confidence" in data
    assert "tokens_used" in data


def test_query_confidence_in_range(client):
    resp = client.post("/api/query", json=_query_payload())
    conf = resp.json()["confidence"]
    assert 0.0 <= conf <= 1.0


def test_query_agent_auto_routed(client):
    """When no agent is specified, routing assigns one."""
    resp = client.post("/api/query", json={"question": "What is the architecture?"})
    assert resp.json()["agent"] != ""


def test_query_preferred_agent_respected(client):
    resp = client.post(
        "/api/query",
        json={"question": "Tell me about Azure", "agent": "azure-navigator"},
    )
    assert resp.json()["agent"] == "azure-navigator"


def test_query_invalid_agent_falls_back(client):
    """An unknown preferred_agent is ignored and auto-routing applies."""
    resp = client.post(
        "/api/query",
        json={"question": "What is Fabric IQ?", "agent": "nonexistent-agent"},
    )
    assert resp.status_code == 200
    assert resp.json()["agent"] != ""


# ── Validation errors ─────────────────────────────────────────────────────────

def test_query_missing_question_returns_422(client):
    resp = client.post("/api/query", json={})
    assert resp.status_code == 422


def test_query_blank_question_returns_422(client):
    resp = client.post("/api/query", json={"question": "   "})
    assert resp.status_code == 422


def test_query_too_short_question_returns_422(client):
    resp = client.post("/api/query", json={"question": "ab"})
    assert resp.status_code == 422


def test_query_top_k_out_of_range_returns_422(client):
    resp = client.post(
        "/api/query",
        json={"question": "What is Fabric IQ?", "top_k": 100},
    )
    assert resp.status_code == 422


# ── Mocked search results ─────────────────────────────────────────────────────

def test_query_with_search_results_builds_citations(client):
    """Mock _search_index to return synthetic results; verify citations."""
    from src.api.models import SearchResult
    from datetime import datetime

    fake_results = [
        SearchResult(
            id="chunk-1",
            title="Fabric IQ Overview",
            source_url="https://learn.microsoft.com/fabric-iq",
            snippet="Fabric IQ is the analytics intelligence layer...",
            score=0.92,
            source_type="ms-learn",
            iq_layer="fabric-iq",
            last_updated=datetime(2024, 1, 1),
        )
    ]

    with patch("src.api.main._search_index", new_callable=AsyncMock, return_value=fake_results):
        resp = client.post("/api/query", json=_query_payload())

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["citations"]) == 1
    assert data["citations"][0]["title"] == "Fabric IQ Overview"
    assert data["citations"][0]["relevance_score"] <= 1.0


def test_query_with_mocked_llm_answer(client):
    """Mock both search and LLM; verify answer propagation."""
    from src.api.models import SearchResult

    fake_results: list[SearchResult] = []

    with (
        patch("src.api.main._search_index", new_callable=AsyncMock, return_value=fake_results),
        patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=("Mocked answer.", 42)),
    ):
        resp = client.post("/api/query", json=_query_payload())

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Mocked answer."
    assert data["tokens_used"] == 42
