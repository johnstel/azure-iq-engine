"""
Unit tests for src/engine/tools.py

All external HTTP calls (Azure AI Search, Bing, Foundry) are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine.tools import (
    _build_odata_filter,
    _doc_to_result,
    bing_web_search,
    generate_outcome_doc,
    get_latest_updates,
    get_service_details,
    search_iq_corpus,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_search_response(docs: list[dict]) -> MagicMock:
    """Return a mock httpx.Response with a JSON body matching AI Search format."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"value": docs}
    mock.raise_for_status = MagicMock()
    return mock


def _make_bing_response(pages: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"webPages": {"value": pages}}
    mock.raise_for_status = MagicMock()
    return mock


def _make_foundry_response(content: str) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    mock.raise_for_status = MagicMock()
    return mock


SAMPLE_DOC = {
    "chunk_id": "chunk-001",
    "title": "What is Fabric IQ?",
    "source_url": "https://learn.microsoft.com/fabric-iq",
    "content": "Fabric IQ is Microsoft's intelligence layer for Fabric workloads.",
    "source_type": "microsoft-learn",
    "iq_layer": "fabric-iq",
    "iq_layers": ["fabric-iq"],
    "last_updated": "2025-01-01T00:00:00Z",
    "@search.score": 0.85,
}


# ── _build_odata_filter ───────────────────────────────────────────────────────

class TestBuildOdataFilter:
    def test_returns_none_when_no_constraints(self) -> None:
        assert _build_odata_filter() is None

    def test_single_iq_layer(self) -> None:
        result = _build_odata_filter(iq_layers=["fabric-iq"])
        assert result is not None
        assert "iq_layers/any" in result
        assert "fabric-iq" in result

    def test_multiple_iq_layers_joined_with_or(self) -> None:
        result = _build_odata_filter(iq_layers=["fabric-iq", "work-iq"])
        assert result is not None
        assert " or " in result

    def test_source_type_filter(self) -> None:
        result = _build_odata_filter(source_types=["microsoft-learn"])
        assert result is not None
        assert "source_type eq 'microsoft-learn'" in result

    def test_target_role_filter(self) -> None:
        result = _build_odata_filter(target_role="developer")
        assert result is not None
        assert "target_role eq 'developer'" in result

    def test_min_date_filter(self) -> None:
        result = _build_odata_filter(min_date="2025-01-01T00:00:00Z")
        assert result is not None
        assert "last_updated ge" in result

    def test_combined_filters_joined_with_and(self) -> None:
        result = _build_odata_filter(
            iq_layers=["foundry-iq"],
            source_types=["azure-updates"],
        )
        assert result is not None
        assert " and " in result


# ── _doc_to_result ─────────────────────────────────────────────────────────────

class TestDocToResult:
    def test_maps_standard_fields(self) -> None:
        result = _doc_to_result(SAMPLE_DOC)
        assert result["id"] == "chunk-001"
        assert result["title"] == "What is Fabric IQ?"
        assert result["source_url"] == "https://learn.microsoft.com/fabric-iq"
        assert result["source_type"] == "microsoft-learn"
        assert result["iq_layer"] == "fabric-iq"
        assert result["score"] == 0.85

    def test_snippet_truncated_to_500_chars(self) -> None:
        long_doc = {**SAMPLE_DOC, "content": "x" * 1000}
        result = _doc_to_result(long_doc)
        assert len(result["snippet"]) <= 500

    def test_iq_layer_falls_back_to_iq_layers_list(self) -> None:
        doc = {**SAMPLE_DOC, "iq_layer": None, "iq_layers": ["work-iq"]}
        result = _doc_to_result(doc)
        assert result["iq_layer"] == "work-iq"

    def test_missing_fields_default_to_empty(self) -> None:
        result = _doc_to_result({})
        assert result["id"] == ""
        assert result["title"] == ""
        assert result["score"] == 0.0


# ── search_iq_corpus ──────────────────────────────────────────────────────────

class TestSearchIqCorpus:
    async def test_returns_empty_list_when_search_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "")
        monkeypatch.setenv("SEARCH_API_KEY", "")
        results = await search_iq_corpus("fabric iq")
        assert results == []

    async def test_returns_results_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
        monkeypatch.setenv("SEARCH_API_KEY", "test-key")

        mock_response = _make_search_response([SAMPLE_DOC])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            results = await search_iq_corpus("fabric iq", max_results=1)

        assert len(results) == 1
        assert results[0]["title"] == "What is Fabric IQ?"

    async def test_applies_iq_layer_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
        monkeypatch.setenv("SEARCH_API_KEY", "test-key")

        mock_response = _make_search_response([SAMPLE_DOC])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            await search_iq_corpus("fabric iq", iq_layers=["fabric-iq"])

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs[1]["json"]
        assert "filter" in payload
        assert "fabric-iq" in payload["filter"]

    async def test_returns_empty_list_on_http_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx as _httpx

        monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
        monkeypatch.setenv("SEARCH_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        mock_client.post = AsyncMock(
            side_effect=_httpx.HTTPStatusError(
                "error", request=MagicMock(), response=mock_response
            )
        )

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            results = await search_iq_corpus("fabric iq")

        assert results == []


# ── get_service_details ───────────────────────────────────────────────────────

class TestGetServiceDetails:
    async def test_returns_stub_when_search_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "")
        monkeypatch.setenv("SEARCH_API_KEY", "")
        result = await get_service_details("Azure Synapse Analytics")
        assert result["service_name"] == "Azure Synapse Analytics"
        assert result["results"] == []

    async def test_returns_service_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
        monkeypatch.setenv("SEARCH_API_KEY", "test-key")

        mock_response = _make_search_response([SAMPLE_DOC])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            result = await get_service_details("Azure Fabric")

        assert result["service_name"] == "Azure Fabric"
        assert len(result["results"]) == 1

    async def test_filter_uses_service_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
        monkeypatch.setenv("SEARCH_API_KEY", "test-key")

        mock_response = _make_search_response([])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            await get_service_details("Azure OpenAI")

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs[1]["json"]
        assert "azure_services" in payload["filter"]
        assert "Azure OpenAI" in payload["filter"]


# ── get_latest_updates ────────────────────────────────────────────────────────

class TestGetLatestUpdates:
    async def test_returns_empty_when_search_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "")
        monkeypatch.setenv("SEARCH_API_KEY", "")
        results = await get_latest_updates(days=7)
        assert results == []

    async def test_returns_update_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
        monkeypatch.setenv("SEARCH_API_KEY", "test-key")

        update_doc = {**SAMPLE_DOC, "source_type": "azure-updates"}
        mock_response = _make_search_response([update_doc])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            results = await get_latest_updates(days=7)

        assert len(results) == 1

    async def test_filter_includes_date_cutoff_and_source_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
        monkeypatch.setenv("SEARCH_API_KEY", "test-key")

        mock_response = _make_search_response([])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            await get_latest_updates(days=3, iq_layers=["foundry-iq"])

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs[1]["json"]
        odata = payload.get("filter", "")
        assert "azure-updates" in odata
        assert "last_updated ge" in odata
        assert "foundry-iq" in odata

    async def test_payload_ordered_by_last_updated_desc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
        monkeypatch.setenv("SEARCH_API_KEY", "test-key")

        mock_response = _make_search_response([])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            await get_latest_updates()

        payload = mock_client.post.call_args[1]["json"]
        assert payload.get("orderby") == "last_updated desc"


# ── bing_web_search ───────────────────────────────────────────────────────────

class TestBingWebSearch:
    async def test_returns_empty_when_bing_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BING_API_KEY", "")
        results = await bing_web_search("Microsoft Fabric")
        assert results == []

    async def test_returns_structured_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BING_API_KEY", "bing-test-key")

        bing_pages = [
            {
                "name": "Microsoft Fabric Overview",
                "url": "https://microsoft.com/fabric",
                "snippet": "Microsoft Fabric is an all-in-one analytics solution.",
                "displayUrl": "microsoft.com/fabric",
                "datePublished": "2025-01-15",
            }
        ]
        mock_response = _make_bing_response(bing_pages)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            results = await bing_web_search("Microsoft Fabric", count=1)

        assert len(results) == 1
        assert results[0]["title"] == "Microsoft Fabric Overview"
        assert results[0]["url"] == "https://microsoft.com/fabric"
        assert results[0]["snippet"] == "Microsoft Fabric is an all-in-one analytics solution."

    async def test_passes_market_and_count_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BING_API_KEY", "bing-test-key")

        mock_response = _make_bing_response([])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            await bing_web_search("AI news", market="en-GB", count=3)

        call_kwargs = mock_client.get.call_args
        params = call_kwargs[1]["params"]
        assert params["mkt"] == "en-GB"
        assert params["count"] == "3"

    async def test_returns_empty_list_on_http_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx as _httpx

        monkeypatch.setenv("BING_API_KEY", "bing-test-key")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_client.get = AsyncMock(
            side_effect=_httpx.HTTPStatusError(
                "error", request=MagicMock(), response=mock_response
            )
        )

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            results = await bing_web_search("test")

        assert results == []


# ── generate_outcome_doc ──────────────────────────────────────────────────────

class TestGenerateOutcomeDoc:
    async def test_returns_stub_when_foundry_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FOUNDRY_BASE_URL", "")
        monkeypatch.setenv("FOUNDRY_KEY", "")

        result = await generate_outcome_doc(
            customer_name="Contoso",
            industry="financial-services",
            research_data={},
            iq_recommendations={},
        )
        doc = json.loads(result)
        assert doc["customer_name"] == "Contoso"
        assert "stub" in doc["executive_summary"].lower()

    async def test_returns_llm_content_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FOUNDRY_BASE_URL", "https://ai.azure.com/foundry")
        monkeypatch.setenv("FOUNDRY_KEY", "foundry-test-key")

        expected_doc = json.dumps({
            "customer_name": "Contoso",
            "industry": "financial-services",
            "executive_summary": "Contoso can leverage Foundry IQ for compliance automation.",
            "iq_opportunity_map": {"foundry-iq": "high"},
            "tco_roi": {"savings": "30%"},
            "risk_analysis": {"risk_level": "medium"},
            "competitive_context": {},
            "implementation_roadmap": ["Phase 1: Assessment"],
        })
        mock_response = _make_foundry_response(expected_doc)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            result = await generate_outcome_doc(
                customer_name="Contoso",
                industry="financial-services",
                research_data={"revenue": "$5B"},
                iq_recommendations={"foundry-iq": "compliance automation"},
            )

        assert result == expected_doc

    async def test_includes_customer_name_in_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FOUNDRY_BASE_URL", "https://ai.azure.com/foundry")
        monkeypatch.setenv("FOUNDRY_KEY", "foundry-test-key")

        mock_response = _make_foundry_response('{"customer_name": "Fabrikam"}')
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            await generate_outcome_doc(
                customer_name="Fabrikam",
                industry="retail",
                research_data={},
                iq_recommendations={},
            )

        payload = mock_client.post.call_args[1]["json"]
        user_content = payload["messages"][1]["content"]
        assert "Fabrikam" in user_content

    async def test_returns_error_json_on_http_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx as _httpx

        monkeypatch.setenv("FOUNDRY_BASE_URL", "https://ai.azure.com/foundry")
        monkeypatch.setenv("FOUNDRY_KEY", "foundry-test-key")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client.post = AsyncMock(
            side_effect=_httpx.HTTPStatusError(
                "error", request=MagicMock(), response=mock_response
            )
        )

        with patch("src.engine.tools.httpx.AsyncClient", return_value=mock_client):
            result = await generate_outcome_doc(
                customer_name="ErrorCo",
                industry="tech",
                research_data={},
                iq_recommendations={},
            )

        doc = json.loads(result)
        assert "error" in doc
        assert doc["customer_name"] == "ErrorCo"
