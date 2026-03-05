"""
Function tools for IQ Engine agents.

These are registered with Agent Framework agents via the `tools` parameter.
Each tool is a typed function that the LLM can invoke during reasoning.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_SEARCH_API_VERSION = "2024-07-01"
_OPENAI_API_VERSION = "2024-06-01"
_INDEX_NAME = "iq-engine-index"
_EMBED_DEPLOYMENT = "text-embedding-3-large"
_CHAT_DEPLOYMENT = "gpt-4o"

# ── Internal helpers ───────────────────────────────────────────────────────────


def _search_url(path: str = "docs/search") -> str | None:
    """Build the AI Search endpoint URL, or return None if not configured."""
    endpoint = os.getenv("SEARCH_ENDPOINT", "").rstrip("/")
    if not endpoint:
        return None
    return f"{endpoint}/indexes/{_INDEX_NAME}/{path}?api-version={_SEARCH_API_VERSION}"


def _search_headers() -> dict[str, str] | None:
    """Return AI Search auth headers, or None if API key is not configured."""
    key = os.getenv("SEARCH_API_KEY")
    if not key:
        return None
    return {"api-key": key, "Content-Type": "application/json"}


async def _generate_embedding(text: str) -> list[float] | None:
    """
    Generate a dense embedding vector via Azure AI Foundry (text-embedding-3-large).

    Returns None with a warning log if FOUNDRY credentials are not configured.
    """
    base_url = os.getenv("FOUNDRY_BASE_URL", "").rstrip("/")
    key = os.getenv("FOUNDRY_KEY")
    if not base_url or not key:
        logger.warning(
            "FOUNDRY_BASE_URL or FOUNDRY_KEY not set — skipping query embedding. "
            "Search will fall back to text-only BM25."
        )
        return None

    url = (
        f"{base_url}/openai/deployments/{_EMBED_DEPLOYMENT}"
        f"/embeddings?api-version={_OPENAI_API_VERSION}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                headers={"api-key": key, "Content-Type": "application/json"},
                json={"input": text, "model": _EMBED_DEPLOYMENT},
            )
            if resp.status_code == 200:
                return resp.json()["data"][0]["embedding"]
            logger.warning(
                "Embedding API returned %d: %s", resp.status_code, resp.text[:200]
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding request failed: %s", exc)
    return None


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
    url = _search_url()
    headers = _search_headers()
    if not url or not headers:
        logger.warning(
            "SEARCH_ENDPOINT or SEARCH_API_KEY not configured — returning empty results."
        )
        return []

    # ── Build OData filter ───────────────────────────────────────────────────
    filter_clauses: list[str] = []
    if iq_layers:
        clause = " or ".join(f"iq_layers/any(l: l eq '{l}')" for l in iq_layers)
        filter_clauses.append(f"({clause})")
    if azure_services:
        clause = " or ".join(f"azure_services/any(s: s eq '{s}')" for s in azure_services)
        filter_clauses.append(f"({clause})")
    if source_types:
        clause = " or ".join(f"source_type eq '{st}'" for st in source_types)
        filter_clauses.append(f"({clause})")
    if target_role:
        filter_clauses.append(f"target_roles/any(r: r eq '{target_role}')")

    # ── Generate query embedding for vector leg ──────────────────────────────
    embedding = await _generate_embedding(query)

    payload: dict = {
        "search": query,
        "top": max_results,
        "select": "chunk_id,title,content,source_url,iq_layers,azure_services,source_type",
        "queryType": "semantic",
        "semanticConfiguration": "default",
    }
    if filter_clauses:
        payload["filter"] = " and ".join(filter_clauses)
    if embedding:
        payload["vectorQueries"] = [
            {
                "kind": "vector",
                "vector": embedding,
                "fields": "embedding",
                "k": max_results,
            }
        ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                items = resp.json().get("value", [])
                return [
                    {
                        "title": item.get("title", ""),
                        "content": (item.get("content") or "")[:600],
                        "source_url": item.get("source_url", ""),
                        "score": item.get("@search.score", 0.0),
                        "iq_layers": item.get("iq_layers") or [],
                    }
                    for item in items
                ]
            logger.warning(
                "AI Search returned %d: %s", resp.status_code, resp.text[:300]
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_iq_corpus request failed: %s", exc)

    return []


async def get_service_details(service_name: str) -> dict:
    """
    Get detailed information about a specific Azure service,
    including pricing, SLAs, regions, and Well-Architected guidance.
    """
    # Primary: filter on azure_services collection
    results = await search_iq_corpus(
        query=f"Azure {service_name} overview features pricing SLA capabilities",
        azure_services=[service_name],
        max_results=8,
    )
    if not results:
        # Fallback: broad text search without service-filter
        results = await search_iq_corpus(
            query=f"{service_name} Azure service overview",
            max_results=5,
        )

    if not results:
        return {
            "name": service_name,
            "description": "",
            "iq_layers": [],
            "related_services": [],
            "sources": [],
        }

    # Aggregate IQ layer tags from all results
    iq_layers: set[str] = set()
    for r in results:
        iq_layers.update(r.get("iq_layers") or [])

    description = (results[0].get("content") or "").strip()

    return {
        "name": service_name,
        "description": description,
        "iq_layers": sorted(iq_layers),
        "related_services": [],  # enriched by downstream agents if needed
        "sources": [
            {"title": r["title"], "url": r["source_url"]} for r in results[:3]
        ],
    }


async def get_latest_updates(
    days: int = 7,
    iq_layers: list[str] | None = None,
) -> list[dict]:
    """
    Get the latest Azure updates and IQ-related announcements.
    Filtered to recent content from azure-update or rss source types.
    """
    url = _search_url()
    headers = _search_headers()
    if not url or not headers:
        logger.warning(
            "SEARCH_ENDPOINT or SEARCH_API_KEY not configured — returning empty results."
        )
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    filter_clauses: list[str] = [
        f"published_at ge {cutoff!r}",
        "(source_type eq 'azure-update' or source_type eq 'rss')",
    ]
    if iq_layers:
        clause = " or ".join(f"iq_layers/any(l: l eq '{l}')" for l in iq_layers)
        filter_clauses.append(f"({clause})")

    payload: dict = {
        "search": "*",
        "top": 20,
        "filter": " and ".join(filter_clauses),
        "select": "chunk_id,title,content,source_url,published_at,iq_layers,source_type",
        "orderby": "published_at desc",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                items = resp.json().get("value", [])
                return [
                    {
                        "title": item.get("title", ""),
                        "summary": (item.get("content") or "")[:400],
                        "source_url": item.get("source_url", ""),
                        "published_at": item.get("published_at", ""),
                        "iq_layers": item.get("iq_layers") or [],
                        "source_type": item.get("source_type", ""),
                    }
                    for item in items
                ]
            logger.warning(
                "AI Search returned %d: %s", resp.status_code, resp.text[:300]
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_latest_updates request failed: %s", exc)

    return []


async def bing_web_search(
    query: str,
    market: str = "en-US",
    count: int = 5,
) -> list[dict]:
    """
    Search the web using Grounding with Bing Search (Azure AI Foundry native).

    Uses the chat completions API with ``data_sources`` of type ``bing_grounding``
    for grounded web results.  Falls back to IQ corpus search if Bing grounding
    credentials are not configured.
    """
    base_url = os.getenv("FOUNDRY_BASE_URL", "").rstrip("/")
    foundry_key = os.getenv("FOUNDRY_KEY")
    bing_endpoint = os.getenv("BING_GROUNDING_ENDPOINT", "")
    bing_key = os.getenv("BING_GROUNDING_KEY", "")
    deployment = os.getenv("OPENAI_DEPLOYMENT", "Kimi-K2.5")

    if not all([base_url, foundry_key, bing_endpoint, bing_key]):
        logger.warning(
            "Bing grounding not configured — falling back to IQ corpus search"
        )
        results = await search_iq_corpus(query=query, max_results=count)
        return [
            {
                "title": r["title"],
                "url": r["source_url"],
                "snippet": r["content"],
                "score": r["score"],
            }
            for r in results
        ]

    chat_url = (
        f"{base_url}/openai/deployments/{deployment}"
        f"/chat/completions?api-version=2024-10-21"
    )

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a research assistant. Search the web and return a "
                    "concise summary with key facts, URLs, and source citations."
                ),
            },
            {"role": "user", "content": query},
        ],
        "data_sources": [
            {
                "type": "bing_grounding",
                "parameters": {
                    "endpoint": bing_endpoint,
                    "key": bing_key,
                    "count": count,
                },
            }
        ],
        "temperature": 0.3,
        "max_tokens": 1000,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                chat_url,
                headers={"api-key": foundry_key, "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code != 200:
                logger.warning(
                    "Bing grounding returned %d: %s",
                    resp.status_code,
                    resp.text[:300],
                )
                # Fall back to corpus
                results = await search_iq_corpus(query=query, max_results=count)
                return [
                    {"title": r["title"], "url": r["source_url"],
                     "snippet": r["content"], "score": r["score"]}
                    for r in results
                ]

            data = resp.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            context = message.get("context", {})

            web_results: list[dict] = []
            for cite in context.get("citations", []):
                web_results.append({
                    "title": cite.get("title", ""),
                    "url": cite.get("url", ""),
                    "snippet": cite.get("content", "")[:500],
                    "score": 0.7,
                })

            # Include the grounded answer if no structured citations
            if not web_results and message.get("content"):
                web_results.append({
                    "title": f"Web research: {query[:80]}",
                    "url": "",
                    "snippet": message["content"][:500],
                    "score": 0.6,
                })

            return web_results

    except Exception as exc:  # noqa: BLE001
        logger.warning("bing_web_search grounding request failed: %s", exc)

    # Ultimate fallback
    results = await search_iq_corpus(query=query, max_results=count)
    return [
        {"title": r["title"], "url": r["source_url"],
         "snippet": r["content"], "score": r["score"]}
        for r in results
    ]


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

    Returns a JSON string matching the outcome document schema.
    """
    base_url = os.getenv("FOUNDRY_BASE_URL", "").rstrip("/")
    key = os.getenv("FOUNDRY_KEY")
    if not base_url or not key:
        logger.warning(
            "FOUNDRY_BASE_URL or FOUNDRY_KEY not configured — "
            "returning placeholder outcome document."
        )
        return json.dumps(
            {
                "customer_name": customer_name,
                "industry": industry,
                "executive_summary": (
                    "Azure AI Foundry credentials required to generate this document. "
                    "Set FOUNDRY_BASE_URL and FOUNDRY_KEY environment variables."
                ),
                "iq_opportunity_map": {},
                "recommended_approach": "",
                "success_metrics": [],
                "next_steps": [],
                "error": "FOUNDRY credentials not configured",
            },
            indent=2,
        )

    chat_url = (
        f"{base_url}/openai/deployments/{_CHAT_DEPLOYMENT}"
        f"/chat/completions?api-version={_OPENAI_API_VERSION}"
    )

    system_prompt = (
        "You are an expert Microsoft IQ solution architect specialised in Work IQ, "
        "Fabric IQ, and Foundry IQ. Generate structured, data-driven customer outcome "
        "documents in valid JSON format. Be precise and focused on measurable business value."
    )

    user_prompt = f"""Generate a comprehensive IQ Outcome Document for the following customer.

Customer: {customer_name}
Industry: {industry}

Research Data:
{json.dumps(research_data, indent=2)}

IQ Recommendations:
{json.dumps(iq_recommendations, indent=2)}

Return a JSON object with EXACTLY these fields:
{{
  "customer_name": "<string>",
  "industry": "<string>",
  "executive_summary": "<2-3 paragraphs on strategic fit and IQ value proposition>",
  "iq_opportunity_map": {{
    "work_iq":    {{ "opportunities": ["<string>", ...], "priority": "high|medium|low" }},
    "fabric_iq":  {{ "opportunities": ["<string>", ...], "priority": "high|medium|low" }},
    "foundry_iq": {{ "opportunities": ["<string>", ...], "priority": "high|medium|low" }}
  }},
  "recommended_approach": "<phased implementation plan with timeline>",
  "success_metrics": ["<KPI string>", ...],
  "next_steps": ["<immediate action>", ...]
}}

Return ONLY valid JSON. No markdown fences, no commentary.""".strip()

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                chat_url,
                headers={"api-key": key, "Content-Type": "application/json"},
                json={
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                    "max_tokens": 2000,
                },
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                # Validate it parses before returning
                parsed = json.loads(raw)
                return json.dumps(parsed, indent=2)
            logger.warning(
                "Chat completion returned %d: %s", resp.status_code, resp.text[:300]
            )
    except json.JSONDecodeError as exc:
        logger.warning("Outcome doc response was not valid JSON: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("generate_outcome_doc request failed: %s", exc)

    return json.dumps(
        {
            "customer_name": customer_name,
            "industry": industry,
            "executive_summary": "Document generation failed — see application logs for details.",
            "iq_opportunity_map": {},
            "recommended_approach": "",
            "success_metrics": [],
            "next_steps": [],
            "error": "Generation failed",
        },
        indent=2,
    )
