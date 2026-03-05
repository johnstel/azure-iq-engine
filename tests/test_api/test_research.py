"""
Tests for POST /api/research endpoint.

Bing Search and Azure OpenAI are mocked — no real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


def _research_payload(**overrides) -> dict:
    base = {"company": "Contoso", "industry": "manufacturing"}
    base.update(overrides)
    return base


# ── Graceful degradation ──────────────────────────────────────────────────────

def test_research_no_credentials_returns_200(client):
    resp = client.post("/api/research", json=_research_payload())
    assert resp.status_code == 200


def test_research_response_schema(client):
    resp = client.post("/api/research", json=_research_payload())
    data = resp.json()
    assert "company" in data
    assert "summary" in data
    assert "iq_opportunities" in data
    assert "recommended_approach" in data
    assert "citations" in data
    assert "tokens_used" in data


def test_research_company_echoed(client):
    resp = client.post("/api/research", json={"company": "FabrikamCorp"})
    assert resp.json()["company"] == "FabrikamCorp"


# ── Validation ────────────────────────────────────────────────────────────────

def test_research_missing_company_returns_422(client):
    resp = client.post("/api/research", json={})
    assert resp.status_code == 422


def test_research_blank_company_returns_422(client):
    resp = client.post("/api/research", json={"company": "   "})
    assert resp.status_code == 422


# ── Mocked LLM with valid JSON ────────────────────────────────────────────────

def test_research_parses_llm_json_response(client):
    """When LLM returns valid JSON, it is parsed into structured fields."""
    llm_json = (
        '{"summary": "Contoso is a manufacturing leader.", '
        '"iq_opportunities": [{"layer": "fabric-iq", "title": "Data Analytics", '
        '"description": "Enable real-time analytics.", "services": ["Microsoft Fabric"], '
        '"priority": "high"}], '
        '"recommended_approach": "Start with a Fabric pilot."}'
    )

    with (
        patch("src.api.main._bing_search", new_callable=AsyncMock, return_value=[]),
        patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
        patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(llm_json, 100)),
    ):
        resp = client.post("/api/research", json=_research_payload())

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == "Contoso is a manufacturing leader."
    assert len(data["iq_opportunities"]) == 1
    opp = data["iq_opportunities"][0]
    assert opp["layer"] == "fabric-iq"
    assert opp["priority"] == "high"
    assert data["recommended_approach"] == "Start with a Fabric pilot."


def test_research_handles_invalid_llm_json_gracefully(client):
    """If LLM returns non-JSON, the raw text is used as summary without crashing."""
    with (
        patch("src.api.main._bing_search", new_callable=AsyncMock, return_value=[]),
        patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
        patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=("Not JSON at all.", 50)),
    ):
        resp = client.post("/api/research", json=_research_payload())

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == "Not JSON at all."
    assert data["iq_opportunities"] == []
