"""
Function tools for IQ Engine agents.

These are registered with Agent Framework agents via the `tools` parameter.
Each tool is a typed function that the LLM can invoke during reasoning.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.api.settings import get_settings

logger = logging.getLogger(__name__)

# ── Shared helpers ─────────────────────────────────────────────────────────────

_SEARCH_API_VERSION = "2024-07-01"


def _search_headers(api_key: str) -> dict[str, str]:
    return {"api-key": api_key, "Content-Type": "application/json"}


def _search_url(endpoint: str, index_name: str, action: str = "search") -> str:
    base = endpoint.rstrip("/")
    return f"{base}/indexes/{index_name}/docs/{action}?api-version={_SEARCH_API_VERSION}"


def _build_odata_filter(
    iq_layers: list[str] | None = None,
    azure_services: list[str] | None = None,
    source_types: list[str] | None = None,
    target_role: str | None = None,
    min_date: str | None = None,
) -> str | None:
    """Build an OData $filter string from optional field constraints."""
    clauses: list[str] = []

    if iq_layers:
        layer_filters = " or ".join(
            f"iq_layers/any(l: l eq '{layer}')" for layer in iq_layers
        )
        clauses.append(f"({layer_filters})")

    if azure_services:
        svc_filters = " or ".join(
            f"azure_services/any(s: s eq '{svc}')" for svc in azure_services
        )
        clauses.append(f"({svc_filters})")

    if source_types:
        src_filters = " or ".join(f"source_type eq '{st}'" for st in source_types)
        clauses.append(f"({src_filters})")

    if target_role:
        clauses.append(f"target_role eq '{target_role}'")

    if min_date:
        clauses.append(f"last_updated ge {min_date}")

    return " and ".join(clauses) if clauses else None


def _doc_to_result(doc: dict[str, Any], score_key: str = "@search.score") -> dict[str, Any]:
    """Map a raw AI Search document to a normalised result dict."""
    return {
        "id": doc.get("chunk_id", ""),
        "title": doc.get("title", ""),
        "source_url": doc.get("source_url", ""),
        "snippet": doc.get("content", "")[:500],
        "score": doc.get(score_key, 0.0),
        "source_type": doc.get("source_type"),
        "iq_layer": doc.get("iq_layer") or (
            doc.get("iq_layers", [None])[0] if doc.get("iq_layers") else None
        ),
        "last_updated": doc.get("last_updated"),
        "metadata": {
            k: v
            for k, v in doc.items()
            if k
            not in {
                "chunk_id",
                "title",
                "source_url",
                "content",
                score_key,
                "source_type",
                "iq_layer",
                "iq_layers",
                "last_updated",
                "embedding",
            }
        },
    }


# ── Tool implementations ───────────────────────────────────────────────────────

async def search_iq_corpus(
    query: str,
    iq_layers: list[str] | None = None,
    azure_services: list[str] | None = None,
    source_types: list[str] | None = None,
    target_role: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Search the IQ knowledge corpus using hybrid vector + BM25 search
    with semantic reranking and scoring profiles.

    Args:
        query: Natural language search query
        iq_layers: Filter by IQ layer(s) — "work-iq", "fabric-iq", "foundry-iq"
        azure_services: Filter by Azure service(s)
        source_types: Filter by source — "ms-learn", "video-transcript", "azure-update", etc.
        target_role: Filter by audience role — "business-leader", "developer", etc.
        max_results: Number of results to return
    """
    settings = get_settings()

    if not settings.has_search:
        logger.warning("Azure AI Search not configured — returning empty results.")
        return []

    odata_filter = _build_odata_filter(
        iq_layers=iq_layers,
        azure_services=azure_services,
        source_types=source_types,
        target_role=target_role,
    )

    payload: dict[str, Any] = {
        "search": query,
        "top": max_results,
        "queryType": "semantic",
        "semanticConfiguration": "default",
        "select": "chunk_id,title,source_url,content,source_type,iq_layer,iq_layers,last_updated",
    }
    if odata_filter:
        payload["filter"] = odata_filter

    url = _search_url(settings.search_endpoint, settings.search_index_name)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=_search_headers(settings.search_api_key),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("AI Search HTTP error %d: %s", exc.response.status_code, exc.response.text[:300])
        return []
    except httpx.RequestError as exc:
        logger.error("AI Search request error: %s", exc)
        return []

    results = [_doc_to_result(doc) for doc in data.get("value", [])]
    logger.info("search_iq_corpus: query=%r returned %d results.", query, len(results))
    return results


async def get_service_details(service_name: str) -> dict:
    """
    Get detailed information about a specific Azure service,
    including pricing, SLAs, regions, and Well-Architected guidance.
    """
    settings = get_settings()

    if not settings.has_search:
        logger.warning("Azure AI Search not configured — returning empty service details.")
        return {"service_name": service_name, "results": []}

    payload: dict[str, Any] = {
        "search": service_name,
        "top": 10,
        "queryType": "semantic",
        "semanticConfiguration": "default",
        "select": "chunk_id,title,source_url,content,source_type,iq_layer,iq_layers,last_updated,azure_services",
        "filter": f"azure_services/any(s: s eq '{service_name}')",
    }

    url = _search_url(settings.search_endpoint, settings.search_index_name)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=_search_headers(settings.search_api_key),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("AI Search HTTP error %d: %s", exc.response.status_code, exc.response.text[:300])
        return {"service_name": service_name, "results": []}
    except httpx.RequestError as exc:
        logger.error("AI Search request error: %s", exc)
        return {"service_name": service_name, "results": []}

    results = [_doc_to_result(doc) for doc in data.get("value", [])]
    logger.info("get_service_details: service=%r returned %d chunks.", service_name, len(results))
    return {"service_name": service_name, "results": results}


async def get_latest_updates(
    days: int = 7,
    iq_layers: list[str] | None = None,
) -> list[dict]:
    """
    Get the latest Azure updates and IQ-related announcements.
    Filtered to recent content from azure-update source type.
    """
    settings = get_settings()

    if not settings.has_search:
        logger.warning("Azure AI Search not configured — returning empty updates.")
        return []

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    # ISO 8601 datetime string (AI Search OData datetime literal)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    odata_filter = _build_odata_filter(
        iq_layers=iq_layers,
        source_types=["azure-updates"],
        min_date=cutoff_str,
    )

    payload: dict[str, Any] = {
        "search": "*",
        "top": 20,
        "orderby": "last_updated desc",
        "select": "chunk_id,title,source_url,content,source_type,iq_layer,iq_layers,last_updated",
    }
    if odata_filter:
        payload["filter"] = odata_filter

    url = _search_url(settings.search_endpoint, settings.search_index_name)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=_search_headers(settings.search_api_key),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("AI Search HTTP error %d: %s", exc.response.status_code, exc.response.text[:300])
        return []
    except httpx.RequestError as exc:
        logger.error("AI Search request error: %s", exc)
        return []

    results = [_doc_to_result(doc) for doc in data.get("value", [])]
    logger.info("get_latest_updates: days=%d returned %d results.", days, len(results))
    return results


async def bing_web_search(
    query: str,
    market: str = "en-US",
    count: int = 5,
) -> list[dict]:
    """
    Search the web via Bing API for customer research,
    competitive analysis, and current events.
    """
    settings = get_settings()

    if not settings.has_bing:
        logger.warning("Bing API key not configured — returning empty results.")
        return []

    params = {
        "q": query,
        "mkt": market,
        "count": str(count),
        "responseFilter": "Webpages",
        "safeSearch": "Moderate",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                settings.bing_endpoint,
                headers={
                    "Ocp-Apim-Subscription-Key": settings.bing_api_key,
                    "Accept": "application/json",
                },
                params=params,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Bing Search HTTP error %d: %s", exc.response.status_code, exc.response.text[:300])
        return []
    except httpx.RequestError as exc:
        logger.error("Bing Search request error: %s", exc)
        return []

    web_pages = data.get("webPages", {}).get("value", [])
    results = [
        {
            "title": page.get("name", ""),
            "url": page.get("url", ""),
            "snippet": page.get("snippet", ""),
            "display_url": page.get("displayUrl", ""),
            "date_published": page.get("datePublished"),
        }
        for page in web_pages
    ]
    logger.info("bing_web_search: query=%r returned %d results.", query, len(results))
    return results


async def generate_outcome_doc(
    customer_name: str,
    industry: str,
    research_data: dict,
    iq_recommendations: dict,
) -> str:
    """
    Generate a customer outcome document using the v3.0 template.
    Includes executive summary, IQ opportunity map, TCO/ROI,
    risk analysis, competitive context, and implementation roadmap.
    """
    settings = get_settings()

    if not settings.has_foundry:
        logger.warning("Foundry not configured — returning stub outcome document.")
        return json.dumps(
            {
                "customer_name": customer_name,
                "industry": industry,
                "executive_summary": "Foundry not configured — stub document.",
                "iq_opportunity_map": {},
                "tco_roi": {},
                "risk_analysis": {},
                "competitive_context": {},
                "implementation_roadmap": [],
            }
        )

    system_prompt = (
        "You are an expert Microsoft IQ solution architect. "
        "Generate a structured customer outcome document in JSON format following the v3.0 template. "
        "Return ONLY valid JSON with these top-level keys: "
        "customer_name, industry, executive_summary, iq_opportunity_map, "
        "tco_roi, risk_analysis, competitive_context, implementation_roadmap."
    )

    user_prompt = (
        f"Customer: {customer_name}\n"
        f"Industry: {industry}\n\n"
        f"Research data:\n{json.dumps(research_data, indent=2)}\n\n"
        f"IQ recommendations:\n{json.dumps(iq_recommendations, indent=2)}\n\n"
        "Generate a complete outcome document following the v3.0 template."
    )

    payload = {
        "model": settings.openai_deployment,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }

    base = settings.foundry_base_url.rstrip("/")
    url = (
        f"{base}/openai/deployments/{settings.openai_deployment}"
        "/chat/completions?api-version=2024-06-01"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers={
                    "api-key": settings.foundry_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Foundry HTTP error %d: %s", exc.response.status_code, exc.response.text[:300])
        return json.dumps({"error": "Foundry API error", "customer_name": customer_name})
    except httpx.RequestError as exc:
        logger.error("Foundry request error: %s", exc)
        return json.dumps({"error": "Network error", "customer_name": customer_name})

    content = data["choices"][0]["message"]["content"]
    logger.info("generate_outcome_doc: generated outcome doc for customer=%r.", customer_name)
    return content
