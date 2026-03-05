"""
Azure IQ Engine — FastAPI Application

Entry point for the MVP API. Exposes:
  Health / Info  →  GET /health, GET /info
  Query          →  POST /api/query
  Research       →  POST /api/research
  Search         →  GET  /api/search
  Sources        →  GET  /api/sources
  Ingestion      →  POST /api/ingest/run, GET /api/ingest/status/{job_id}

All Azure credentials arrive via environment variables (see settings.py).
Run locally:
    uvicorn src.api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .cache import (
    TTL_LLM,
    TTL_SEARCH,
    get_cached,
    invalidate_pattern,
    make_cache_key,
    set_cached,
)
from .telemetry import get_metrics, get_tracer, init_telemetry
from .models import (
    HealthResponse,
    InfoResponse,
    IngestJobStatus,
    IngestRunRequest,
    IQOpportunity,
    QueryRequest,
    QueryResponse,
    ResearchRequest,
    ResearchResponse,
    SearchResponse,
    SearchResult,
    Citation,
    SourceStats,
    SourcesResponse,
)
from .rate_limit import RateLimitMiddleware, RateLimitRule
from .router_query import list_agents, route_question
from .settings import get_settings
from pydantic import BaseModel as _BaseModel


class CacheInvalidateRequest(_BaseModel):
    """Body for POST /api/cache/invalidate."""
    pattern: str = "*"  # glob pattern; defaults to clearing everything

logger = logging.getLogger(__name__)

# ── In-process job store (MVP) ────────────────────────────────────────────────
# Replace with Azure Table Storage or Service Bus for production.
_jobs: dict[str, IngestJobStatus] = {}


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "Azure IQ Engine %s starting — foundry=%s, search=%s",
        settings.app_version,
        bool(settings.foundry_base_url),
        bool(settings.search_endpoint),
    )

    # Initialise Application Insights telemetry (no-op if env var absent)
    init_telemetry(settings.applicationinsights_connection_string or None)

    # Initialise Agent Framework agents and multi-agent workflows.
    # Agents are stored in app.state so every request handler can access them
    # without re-creating the client on every call.
    app.state.agents: dict[str, Any] = {}
    app.state.workflows: dict[str, Any] = {}

    if settings.has_foundry:
        try:
            from agent_framework.azure import AzureOpenAIResponsesClient  # type: ignore[import]
            from ..engine.agents import create_agents, create_workflows

            # Prefer API key auth (FOUNDRY_KEY) over DefaultAzureCredential
            # to avoid Managed Identity issues in Container Apps.
            foundry_key = settings.foundry_key
            if foundry_key:
                from azure.core.credentials import AzureKeyCredential  # type: ignore[import]
                credential = AzureKeyCredential(foundry_key)
            else:
                from azure.identity import DefaultAzureCredential  # type: ignore[import]
                credential = DefaultAzureCredential()

            client = AzureOpenAIResponsesClient(
                credential=credential,
                endpoint=settings.foundry_base_url,
            )
            app.state.agents = create_agents(client)
            app.state.workflows = create_workflows(app.state.agents)
            logger.info(
                "Agent Framework initialised — agents=%s  workflows=%s",
                list(app.state.agents),
                list(app.state.workflows),
            )
        except ImportError:
            logger.warning(
                "agent-framework package not installed — "
                "agent routing will use direct RAG fallback"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent Framework initialisation failed: %s", exc, exc_info=True)
    else:
        logger.warning("FOUNDRY_BASE_URL not configured — Agent Framework agents disabled")

    yield
    logger.info("Azure IQ Engine shutting down.")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS — allow all for MVP; restrict in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.add_middleware(
        RateLimitMiddleware,
        rules=[
            RateLimitRule(
                path_prefix="/api/query",
                rpm=settings.rate_limit_query_rpm,
            ),
            RateLimitRule(
                path_prefix="/api/research",
                rpm=settings.rate_limit_research_rpm,
            ),
        ],
    )

    @app.middleware("http")
    async def _telemetry_middleware(request: Request, call_next):
        """Attach a span to every inbound HTTP request for distributed tracing."""
        tracer = get_tracer()
        span_name = f"{request.method} {request.url.path}"
        with tracer.start_as_current_span(span_name) as span:  # type: ignore[attr-defined]
            span.set_attribute("http.method", request.method)  # type: ignore[attr-defined]
            span.set_attribute("http.url", str(request.url))  # type: ignore[attr-defined]
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)  # type: ignore[attr-defined]
        return response

    return app


app = create_app()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _search_index(
    query: str,
    *,
    top: int = 5,
    source_type: str | None = None,
    iq_layer: str | None = None,
) -> list[SearchResult]:
    """
    Query Azure AI Search and return structured results.

    Returns an empty list when SEARCH_ENDPOINT is not configured so the
    app degrades gracefully during local development.
    """
    settings = get_settings()
    if not settings.has_search:
        logger.warning("SEARCH_ENDPOINT not configured — returning empty results")
        return []

    endpoint = (
        f"{settings.search_endpoint}/indexes/{settings.search_index_name}"
        f"/docs/search?api-version=2024-07-01"
    )

    # Build OData filter
    filters: list[str] = []
    if source_type:
        filters.append(f"source_type eq '{source_type}'")
    if iq_layer:
        filters.append(f"iq_layers/any(l: l eq '{iq_layer}')")
    filter_expr = " and ".join(filters) if filters else None

    body: dict[str, Any] = {
        "search": query,
        "queryType": "semantic",
        "semanticConfiguration": "default-semantic",
        "top": top,
        "select": "chunk_id,title,source_url,content,source_type,iq_layers,published_at,heading_path,video_id,video_start_time,video_end_time",
        "captions": "extractive",
        "answers": "extractive|count-3",
    }
    if filter_expr:
        body["filter"] = filter_expr

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                endpoint,
                json=body,
                headers={
                    "api-key": settings.search_api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.error("AI Search request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Search service unavailable")

    results: list[SearchResult] = []
    for doc in data.get("value", []):
        caption = ""
        captions = doc.get("@search.captions", [])
        if captions:
            caption = captions[0].get("text", "")

        # Build source URL with timestamp for video content
        raw_url = doc.get("source_url", "")
        vid_id = doc.get("video_id")
        vid_start = doc.get("video_start_time")
        if vid_id and not raw_url.startswith("http"):
            raw_url = f"https://www.youtube.com/watch?v={vid_id}"
        if vid_id and vid_start is not None and "youtube.com" in raw_url:
            raw_url = f"https://www.youtube.com/watch?v={vid_id}&t={int(vid_start)}"

        results.append(
            SearchResult(
                id=doc.get("chunk_id", ""),
                title=doc.get("title", "Untitled"),
                source_url=raw_url,
                snippet=caption or doc.get("content", "")[:300],
                score=doc.get("@search.score", 0.0),
                source_type=doc.get("source_type"),
                iq_layer=", ".join(doc.get("iq_layers", [])) if doc.get("iq_layers") else None,
                last_updated=doc.get("published_at"),
                video_id=vid_id,
                video_start_time=vid_start,
                video_end_time=doc.get("video_end_time"),
                metadata={"heading_path": doc.get("heading_path", "")},
            )
        )

    return results


def _results_to_citations(results: list[SearchResult]) -> list[Citation]:
    return [
        Citation(
            source_url=r.source_url,
            title=r.title,
            relevance_score=min(r.score, 1.0),
            snippet=r.snippet,
            source_type=r.source_type,
            iq_layer=r.iq_layer,
            video_start_time=r.video_start_time,
        )
        for r in results
    ]


async def _call_openai(
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int]:
    """
    Call Azure OpenAI via the Foundry endpoint.

    Returns (answer_text, tokens_used).
    Degrades gracefully when FOUNDRY_BASE_URL is not set.
    """
    settings = get_settings()
    if not settings.has_foundry:
        logger.warning("FOUNDRY_BASE_URL not configured — returning stub answer")
        return (
            "[Azure AI Foundry not configured — set FOUNDRY_BASE_URL and FOUNDRY_KEY]",
            0,
        )

    endpoint = (
        f"{settings.foundry_base_url}/openai/deployments/"
        f"{settings.openai_deployment}/chat/completions"
        f"?api-version=2024-08-01-preview"
    )

    body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 2000,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                endpoint,
                json=body,
                headers={
                    "api-key": settings.foundry_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.error("OpenAI request failed: %s", exc)
        raise HTTPException(status_code=502, detail="LLM service unavailable")

    answer = data["choices"][0]["message"]["content"]
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return answer, tokens


def _build_rag_prompt(question: str, results: list[SearchResult]) -> tuple[str, str]:
    """Build system + user prompts with grounded context."""
    context_blocks = "\n\n".join(
        f"[{i + 1}] {r.title}\nURL: {r.source_url}\n{r.snippet}"
        for i, r in enumerate(results)
    )

    system_prompt = (
        "You are the Azure IQ Engine — a grounded AI assistant specialised in "
        "Microsoft's IQ layer stack (Work IQ, Fabric IQ, Foundry IQ) and Azure services. "
        "Answer questions using ONLY the provided context. "
        "Cite sources by their [number]. "
        "If the context is insufficient, say so clearly rather than hallucinating. "
        "Be precise, structured, and authoritative."
    )

    user_prompt = (
        f"## Context\n{context_blocks}\n\n"
        f"## Question\n{question}\n\n"
        "Answer using the context above. Cite sources as [1], [2], etc."
    )

    return system_prompt, user_prompt


def _extract_iq_layers(text: str) -> list[str]:
    """Heuristically identify IQ layers mentioned in a response."""
    layers = []
    lower = text.lower()
    if "work iq" in lower:
        layers.append("work-iq")
    if "fabric iq" in lower:
        layers.append("fabric-iq")
    if "foundry iq" in lower:
        layers.append("foundry-iq")
    return layers or ["work-iq", "fabric-iq", "foundry-iq"]


async def _bing_search(query: str, count: int = 5) -> list[Citation]:
    """
    Search the web via Grounding with Bing Search (Azure AI Foundry native).

    Uses the chat completions API with a ``data_sources`` extension of type
    ``bing_grounding`` so the LLM receives grounded web context.  Citations
    are extracted from the ``context.citations`` block in the response.
    """
    settings = get_settings()
    if not settings.has_bing:
        logger.warning(
            "BING_GROUNDING_KEY/ENDPOINT not configured — skipping web search"
        )
        return []

    # Build the chat completions request with Bing grounding data source
    chat_url = (
        f"{settings.foundry_base_url}/openai/deployments/{settings.openai_deployment}"
        f"/chat/completions?api-version=2024-10-21"
    )

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a research assistant. Search the web for the user's "
                    "query and return a concise summary with source citations."
                ),
            },
            {"role": "user", "content": query},
        ],
        "data_sources": [
            {
                "type": "bing_grounding",
                "parameters": {
                    "endpoint": settings.bing_grounding_endpoint,
                    "key": settings.bing_grounding_key,
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
                headers={
                    "api-key": settings.foundry_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Grounding with Bing search failed: %s", exc)
        return []

    # Extract citations from the response context
    citations: list[Citation] = []
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    context = message.get("context", {})

    for cite in context.get("citations", []):
        citations.append(
            Citation(
                source_url=cite.get("url", ""),
                title=cite.get("title", ""),
                relevance_score=0.7,
                snippet=cite.get("content", "")[:500],
                source_type="bing-grounding",
            )
        )

    # If no structured citations, at least return the grounded answer as context
    if not citations and message.get("content"):
        citations.append(
            Citation(
                source_url="",
                title=f"Web research: {query[:80]}",
                relevance_score=0.6,
                snippet=message["content"][:500],
                source_type="bing-grounding",
            )
        )

    return citations


async def _run_agent_loop(agent: Any, message: str) -> tuple[str | None, int]:
    """
    Execute an Agent Framework agent or workflow's tool-calling loop.

    Tries the most common async and sync run/invoke method names in order.
    Returns ``(answer_text, tokens_used)`` on success, or ``(None, 0)`` when
    the agent is unavailable or raises an exception, so the caller can fall
    back to the plain RAG path.
    """
    try:
        if hasattr(agent, "run_async"):
            resp = await agent.run_async(message)
        elif hasattr(agent, "invoke_async"):
            resp = await agent.invoke_async(message)
        elif hasattr(agent, "run"):
            result = agent.run(message)
            resp = await result if asyncio.iscoroutine(result) else result
        elif hasattr(agent, "invoke"):
            result = agent.invoke(message)
            resp = await result if asyncio.iscoroutine(result) else result
        else:
            logger.warning("Agent has no recognised run/invoke method — skipping")
            return None, 0

        # Normalise the response to (text, tokens).
        if isinstance(resp, str):
            return resp, 0

        answer: str = (
            getattr(resp, "output", None)
            or getattr(resp, "text", None)
            or getattr(resp, "content", None)
            or str(resp)
        )
        usage = getattr(resp, "usage", None)
        tokens: int = 0
        if isinstance(usage, dict):
            tokens = int(usage.get("total_tokens", 0))
        elif usage is not None:
            tokens = int(getattr(usage, "total_tokens", 0))

        return answer, tokens

    except Exception as exc:  # noqa: BLE001
        logger.warning("Agent/workflow run failed (%s) — falling back to RAG", exc, exc_info=True)
        return None, 0


def _parse_research_json(
    raw: str,
    *,
    fallback_summary: str,
) -> tuple[str, list[IQOpportunity], str]:
    """
    Parse a JSON research response produced by the LLM or a workflow.

    Returns ``(summary, opportunities, recommended_approach)``.
    Falls back gracefully when *raw* is not valid JSON.
    """
    default_approach = "Engage IQ specialist for detailed discovery."
    try:
        parsed = json.loads(raw)
        summary = parsed.get("summary", fallback_summary)
        recommended_approach = parsed.get("recommended_approach", default_approach)
        opportunities: list[IQOpportunity] = [
            IQOpportunity(
                layer=opp.get("layer", "foundry-iq"),
                title=opp.get("title", ""),
                description=opp.get("description", ""),
                services=opp.get("services", []),
                priority=opp.get("priority", "medium"),
            )
            for opp in parsed.get("iq_opportunities", [])
        ]
        return summary, opportunities, recommended_approach
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Could not parse LLM JSON response for research: %s", exc)
        return fallback_summary, [], default_approach


# ── Background ingestion task ─────────────────────────────────────────────────

async def _run_ingestion(job_id: str, req: IngestRunRequest) -> None:
    """
    Lightweight background ingestion stub.

    For a real implementation, import and call the ingestion orchestrator
    from src/ingestion/orchestrator.py.
    """
    job = _jobs[job_id]

    try:
        # Simulate staged progress
        await asyncio.sleep(1)
        job.status = "running"
        job.progress_pct = 10.0

        if not req.dry_run:
            # Import here to avoid circular deps at module load time
            try:
                from ..ingestion.orchestrator import run_ingestion  # type: ignore[import]

                result = await run_ingestion(
                    sources=req.sources,
                    force_recrawl=req.force_recrawl,
                )
                job.documents_processed = result.get("documents", 0)
                job.chunks_indexed = result.get("chunks", 0)
            except ImportError:
                logger.warning(
                    "Ingestion orchestrator not available — dry-run simulation only"
                )
                await asyncio.sleep(3)
                job.documents_processed = 0
                job.chunks_indexed = 0

        job.progress_pct = 100.0
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        logger.info("Ingestion job %s completed", job_id)

        # Record chunk telemetry
        get_metrics().ingestion_chunks.add(  # type: ignore[attr-defined]
            job.chunks_indexed or 0,
            {"job_id": job_id},
        )

    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.errors.append(str(exc))
        job.completed_at = datetime.now(timezone.utc)
        logger.exception("Ingestion job %s failed", job_id)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    """Serve the web UI (falls back to Swagger if no static file)."""
    import pathlib
    static_dir = pathlib.Path(__file__).resolve().parent.parent / "static"
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html")
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health() -> HealthResponse:
    """Liveness check — always 200 when the process is alive."""
    return HealthResponse(version=get_settings().app_version)


@app.get("/info", response_model=InfoResponse, tags=["Health"])
async def info() -> InfoResponse:
    """Return app metadata including registered agents and sources."""
    settings = get_settings()
    agents = [a["name"] for a in list_agents()]
    return InfoResponse(
        name=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
        sources=settings.content_sources,
        agents=agents,
        iq_layers=settings.iq_layers,
    )


# ── Query ─────────────────────────────────────────────────────────────────────

@app.post("/api/query", tags=["Query"])
async def query_endpoint(req: QueryRequest, request: Request) -> Response:
    """
    Main Q&A endpoint.

    Routes the question to the selected Agent Framework specialist agent whose
    tool-calling loop handles search and reasoning internally. Falls back to a
    direct search → RAG path when the Agent Framework is unavailable (e.g. the
    agent-framework package is not installed or Foundry credentials are absent).

    Responses are cached in Redis (TTL_SEARCH) and the X-Cache header indicates
    HIT or MISS.
    """
    t0 = time.monotonic()
    settings = get_settings()
    telemetry = get_metrics()
    tracer = get_tracer()

    # 1 — Route to the appropriate specialist agent name.
    agent_name = route_question(req.question, preferred_agent=req.agent)

    # 2 — Cache lookup
    cache_key = make_cache_key(
        req.question,
        agent=agent_name,
        filters={"iq_layers": req.iq_layers, "top_k": req.top_k},
    )
    cached_payload = await get_cached(cache_key)
    if cached_payload is not None:
        telemetry.cache_hits.add(1, {"endpoint": "query"})  # type: ignore[attr-defined]
        logger.debug("Cache HIT for query key %s", cache_key[:16])
        return JSONResponse(
            content=cached_payload,
            headers={"X-Cache": "HIT"},
        )

    telemetry.cache_misses.add(1, {"endpoint": "query"})  # type: ignore[attr-defined]

    # 3 — Try Agent Framework tool-calling loop for the selected agent.
    with tracer.start_as_current_span("query.agent_loop") as span:  # type: ignore[attr-defined]
        span.set_attribute("agent", agent_name)  # type: ignore[attr-defined]

        agents: dict[str, Any] = getattr(request.app.state, "agents", {})
        agent = agents.get(agent_name)

        answer: str | None = None
        tokens: int = 0
        results: list[SearchResult] = []

        if agent is not None:
            logger.debug("Routing question to Agent Framework agent '%s'", agent_name)
            answer, tokens = await _run_agent_loop(agent, req.question)

        # 4 — Fall back to direct RAG when the agent is unavailable or failed.
        if answer is None:
            logger.debug("Agent '%s' unavailable — using direct RAG fallback", agent_name)
            results = await _search_index(
                req.question,
                top=req.top_k or settings.search_top_k,
                iq_layer=req.iq_layers[0] if req.iq_layers else None,
            )
            system_prompt, user_prompt = _build_rag_prompt(req.question, results)
            answer, tokens = await _call_openai(system_prompt, user_prompt)

    # 5 — Derive metadata
    citations = _results_to_citations(results)
    iq_layers = _extract_iq_layers(answer)
    confidence = min(
        0.95,
        sum(c.relevance_score for c in citations) / max(len(citations), 1),
    ) if citations else 0.4

    latency_ms = int((time.monotonic() - t0) * 1000)

    # 6 — Record telemetry
    telemetry.query_duration.record(latency_ms, {"endpoint": "query", "agent": agent_name})  # type: ignore[attr-defined]
    telemetry.query_tokens.add(tokens, {"endpoint": "query", "agent": agent_name})  # type: ignore[attr-defined]

    response_obj = QueryResponse(
        answer=answer,
        citations=citations,
        agent=agent_name,
        iq_layers=req.iq_layers or iq_layers,
        confidence=round(confidence, 3),
        tokens_used=tokens,
        latency_ms=latency_ms,
    )

    # 7 — Cache the response payload
    payload = response_obj.model_dump(mode="json")
    await set_cached(cache_key, payload, ttl=TTL_SEARCH)

    return JSONResponse(content=payload, headers={"X-Cache": "MISS"})


# ── Research ──────────────────────────────────────────────────────────────────

@app.post("/api/research", tags=["Research"])
async def research_endpoint(req: ResearchRequest, request: Request) -> Response:
    """
    Customer research endpoint.

    Drives the **customer-outcome** multi-agent workflow:
    customer-researcher → iq-architect → story-weaver (sequential).

    Falls back to direct Bing + AI Search + LLM synthesis when the
    Agent Framework workflow is unavailable.

    Responses are cached in Redis (TTL_LLM) and the X-Cache header indicates
    HIT or MISS.
    """
    t0 = time.monotonic()
    settings = get_settings()
    telemetry = get_metrics()
    tracer = get_tracer()

    # Cache lookup
    cache_key = make_cache_key(
        req.company,
        agent="research",
        filters={"industry": req.industry, "focus_areas": sorted(req.focus_areas or [])},
    )
    cached_payload = await get_cached(cache_key)
    if cached_payload is not None:
        telemetry.cache_hits.add(1, {"endpoint": "research"})  # type: ignore[attr-defined]
        logger.debug("Cache HIT for research key %s", cache_key[:16])
        return JSONResponse(content=cached_payload, headers={"X-Cache": "HIT"})

    telemetry.cache_misses.add(1, {"endpoint": "research"})  # type: ignore[attr-defined]

    # 1 — Attempt the customer-outcome workflow (researcher → architect → story-weaver).
    workflows: dict[str, Any] = getattr(request.app.state, "workflows", {})
    workflow = workflows.get("customer-outcome")

    summary: str | None = None
    opportunities: list[IQOpportunity] = []
    recommended_approach = "Engage IQ specialist for detailed discovery."
    all_citations: list[Citation] = []
    tokens: int = 0

    if workflow is not None:
        focus = ", ".join(req.focus_areas) if req.focus_areas else "general IQ stack"
        research_prompt = (
            f"Research the following customer and generate a structured IQ opportunity assessment.\n"
            f"Company: {req.company}\n"
            f"Industry: {req.industry or 'Not specified'}\n"
            f"Focus areas: {focus}\n\n"
            "Produce a JSON response with keys: summary, iq_opportunities "
            "(each with layer, title, description, services, priority), recommended_approach."
        )
        logger.debug("Running customer-outcome workflow for company '%s'", req.company)
        raw_answer, tokens = await _run_agent_loop(workflow, research_prompt)

        if raw_answer is not None:
            summary, opportunities, recommended_approach = _parse_research_json(
                raw_answer, fallback_summary=raw_answer
            )

    # 2 — Fall back to direct implementation when workflow is unavailable or failed.
    if summary is None:
        logger.debug("customer-outcome workflow unavailable — using direct RAG fallback")

        # Bing search: company context
        bing_query = f"{req.company} Azure AI analytics cloud strategy"
        if req.industry:
            bing_query += f" {req.industry}"
        web_citations = await _bing_search(bing_query, count=5)

        # AI Search: IQ opportunity context
        iq_query = f"IQ opportunities {req.industry or 'enterprise'} {' '.join(req.focus_areas or [])}"
        iq_results = await _search_index(iq_query, top=settings.search_top_k)
        iq_citations = _results_to_citations(iq_results)
        all_citations = web_citations + iq_citations

        context_web = "\n".join(
            f"- {c.title}: {c.snippet}" for c in web_citations
        ) or "No web results available."
        context_iq = "\n\n".join(
            f"[{i + 1}] {r.title}\n{r.snippet}" for i, r in enumerate(iq_results)
        ) or "No IQ corpus results available."
        focus = ", ".join(req.focus_areas) if req.focus_areas else "general IQ stack"

        system_prompt = (
            "You are a Microsoft Azure IQ specialist preparing a customer research brief. "
            "Synthesise the provided web research and IQ corpus context into a structured "
            "opportunity assessment. Be specific about IQ layers (Work IQ, Fabric IQ, "
            "Foundry IQ) and relevant Azure services. Output valid JSON matching this schema:\n"
            '{"summary": "...", "iq_opportunities": [{"layer": "...", "title": "...", '
            '"description": "...", "services": ["..."], "priority": "high|medium|low"}], '
            '"recommended_approach": "..."}'
        )

        user_prompt = (
            f"## Company: {req.company}\n"
            f"## Industry: {req.industry or 'Not specified'}\n"
            f"## Focus Areas: {focus}\n\n"
            f"## Web Research\n{context_web}\n\n"
            f"## IQ Corpus Context\n{context_iq}\n\n"
            "Generate a structured IQ opportunity assessment. "
            "Return ONLY the JSON object, no markdown fences."
        )

        raw_answer, tokens = await _call_openai(system_prompt, user_prompt)
        summary, opportunities, recommended_approach = _parse_research_json(
            raw_answer, fallback_summary=raw_answer
        )

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Record telemetry
    telemetry.query_duration.record(latency_ms, {"endpoint": "research"})  # type: ignore[attr-defined]
    telemetry.query_tokens.add(tokens, {"endpoint": "research"})  # type: ignore[attr-defined]

    response_obj = ResearchResponse(
        company=req.company,
        industry=req.industry,
        summary=summary,
        iq_opportunities=opportunities,
        recommended_approach=recommended_approach,
        citations=all_citations,
        tokens_used=tokens,
        latency_ms=latency_ms,
    )

    # Cache with longer TTL (LLM synthesis is expensive)
    payload = response_obj.model_dump(mode="json")
    await set_cached(cache_key, payload, ttl=TTL_LLM)

    return JSONResponse(content=payload, headers={"X-Cache": "MISS"})


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/api/search", response_model=SearchResponse, tags=["Search"])
async def search_endpoint(
    q: str = Query(..., min_length=1, description="Search query"),
    source_type: str | None = Query(None, description="Filter by source type"),
    iq_layer: str | None = Query(None, description="Filter by IQ layer"),
    top: int = Query(10, ge=1, le=50, description="Number of results to return"),
) -> SearchResponse:
    """
    Direct Azure AI Search pass-through — no LLM involved.

    Useful for exploring the corpus or powering a search UI.
    """
    results = await _search_index(
        q,
        top=top,
        source_type=source_type,
        iq_layer=iq_layer,
    )

    return SearchResponse(
        query=q,
        results=results,
        total=len(results),
        top=top,
        source_type_filter=source_type,
        iq_layer_filter=iq_layer,
    )


# ── Sources ───────────────────────────────────────────────────────────────────

@app.get("/api/sources", response_model=SourcesResponse, tags=["Sources"])
async def sources_endpoint() -> SourcesResponse:
    """
    List available content sources with document and chunk counts.

    Counts are fetched from the Azure AI Search index using faceted queries.
    Falls back to configured source list with zero counts when search is unavailable.
    """
    settings = get_settings()

    # Attempt to get real counts via AI Search facets
    source_stats: list[SourceStats] = []
    total_docs = 0
    total_chunks = 0

    if settings.has_search:
        try:
            facet_endpoint = (
                f"{settings.search_endpoint}/indexes/{settings.search_index_name}"
                f"/docs/search?api-version=2024-07-01"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    facet_endpoint,
                    json={
                        "search": "*",
                        "top": 0,
                        "facets": ["source_type,count:50"],
                        "select": "",
                    },
                    headers={
                        "api-key": settings.search_api_key,
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            facets = data.get("@search.facets", {}).get("source_type", [])
            for facet in facets:
                src_id = facet.get("value", "unknown")
                count = facet.get("count", 0)
                total_chunks += count
                source_stats.append(
                    SourceStats(
                        source_id=src_id,
                        display_name=src_id.replace("-", " ").title(),
                        chunk_count=count,
                        document_count=count,  # chunk ≈ doc at this level for MVP
                        status="active",
                    )
                )
                total_docs += count

        except httpx.HTTPError as exc:
            logger.warning("Could not fetch source facets: %s", exc)

    # Fill in any configured sources not yet in the index
    indexed_ids = {s.source_id for s in source_stats}
    for src_id in settings.content_sources:
        if src_id not in indexed_ids:
            source_stats.append(
                SourceStats(
                    source_id=src_id,
                    display_name=src_id.replace("-", " ").title(),
                    status="idle" if settings.has_search else "unknown",
                )
            )

    return SourcesResponse(
        sources=source_stats,
        total_documents=total_docs,
        total_chunks=total_chunks,
        index_name=settings.search_index_name,
    )


# ── Ingestion ─────────────────────────────────────────────────────────────────

@app.post("/api/ingest/run", response_model=IngestJobStatus, tags=["Ingestion"])
async def ingest_run(req: IngestRunRequest, background_tasks=None) -> IngestJobStatus:
    """
    Trigger an ingestion pipeline run.

    The job runs asynchronously in the background. Poll
    GET /api/ingest/status/{job_id} for progress.
    """
    settings = get_settings()
    sources = req.sources or settings.content_sources
    job_id = str(uuid.uuid4())

    job = IngestJobStatus(
        job_id=job_id,
        status="started",
        sources=sources,
        dry_run=req.dry_run,
        force_recrawl=req.force_recrawl,
        started_at=datetime.now(timezone.utc),
    )
    _jobs[job_id] = job

    # Fire and forget
    asyncio.create_task(_run_ingestion(job_id, req))

    logger.info(
        "Ingestion job %s started — sources=%s dry_run=%s",
        job_id,
        sources,
        req.dry_run,
    )
    return job


@app.get(
    "/api/ingest/status/{job_id}",
    response_model=IngestJobStatus,
    tags=["Ingestion"],
)
async def ingest_status(job_id: str) -> IngestJobStatus:
    """Retrieve the current status of an ingestion job by ID."""
    job = _jobs.get(job_id)
    if not job:
        return IngestJobStatus(job_id=job_id, status="not_found")
    return job


# ── Cache management ──────────────────────────────────────────────────────────

def _require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    """
    Dependency that enforces the ADMIN_API_KEY when it is configured.

    If ADMIN_API_KEY is empty (dev/local), all requests are allowed through.
    """
    settings = get_settings()
    required = settings.admin_api_key
    if required and x_admin_key != required:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Key header")


@app.post(
    "/api/cache/invalidate",
    tags=["Admin"],
    summary="Invalidate cached query results",
    dependencies=[Depends(_require_admin_key)],
)
async def cache_invalidate(req: CacheInvalidateRequest) -> JSONResponse:
    """
    Delete cached entries matching the provided glob *pattern*.

    Defaults to ``"*"`` which flushes the entire query cache.

    Requires the ``X-Admin-Key`` header when ``ADMIN_API_KEY`` is configured.

    Example
    -------
    ```
    POST /api/cache/invalidate
    X-Admin-Key: <your-key>

    {"pattern": "*"}
    ```
    """
    deleted = await invalidate_pattern(req.pattern)
    return JSONResponse(
        content={
            "pattern": req.pattern,
            "keys_deleted": deleted,
            "status": "ok",
        }
    )
