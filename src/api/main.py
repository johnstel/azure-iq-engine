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
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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
        f"/docs/search?api-version=2024-05-01-preview"
    )

    # Build OData filter
    filters: list[str] = []
    if source_type:
        filters.append(f"source_type eq '{source_type}'")
    if iq_layer:
        filters.append(f"iq_layer eq '{iq_layer}'")
    filter_expr = " and ".join(filters) if filters else None

    body: dict[str, Any] = {
        "search": query,
        "queryType": "semantic",
        "semanticConfiguration": "default",
        "top": top,
        "select": "id,title,source_url,content,source_type,iq_layer,last_updated",
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

        results.append(
            SearchResult(
                id=doc.get("id", ""),
                title=doc.get("title", "Untitled"),
                source_url=doc.get("source_url", ""),
                snippet=caption or doc.get("content", "")[:300],
                score=doc.get("@search.score", 0.0),
                source_type=doc.get("source_type"),
                iq_layer=doc.get("iq_layer"),
                last_updated=doc.get("last_updated"),
                metadata={},
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
    """Perform a Bing Web Search and return citations."""
    settings = get_settings()
    if not settings.has_bing:
        logger.warning("BING_API_KEY not configured — skipping web search")
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                settings.bing_endpoint,
                params={"q": query, "count": count, "mkt": "en-US"},
                headers={"Ocp-Apim-Subscription-Key": settings.bing_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Bing search failed: %s", exc)
        return []

    citations: list[Citation] = []
    for page in data.get("webPages", {}).get("value", []):
        citations.append(
            Citation(
                source_url=page.get("url", ""),
                title=page.get("name", ""),
                relevance_score=0.7,
                snippet=page.get("snippet", ""),
                source_type="bing-web",
            )
        )
    return citations


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

@app.post("/api/query", response_model=QueryResponse, tags=["Query"])
async def query_endpoint(req: QueryRequest, request: Request) -> QueryResponse:
    """
    Main Q&A endpoint.

    Retrieves grounded context from Azure AI Search, builds a cited prompt,
    and calls Azure OpenAI for the final answer.
    """
    t0 = time.monotonic()
    settings = get_settings()

    # 1 — Route to agent
    agent = route_question(req.question, preferred_agent=req.agent)

    # 2 — Retrieve context from AI Search
    results = await _search_index(
        req.question,
        top=req.top_k or settings.search_top_k,
        iq_layer=req.iq_layers[0] if req.iq_layers else None,
    )

    # 3 — Build grounded prompt and call LLM
    system_prompt, user_prompt = _build_rag_prompt(req.question, results)
    answer, tokens = await _call_openai(system_prompt, user_prompt)

    # 4 — Derive metadata
    citations = _results_to_citations(results)
    iq_layers = _extract_iq_layers(answer)
    # Simple confidence heuristic based on citation count and score
    confidence = min(
        0.95,
        sum(c.relevance_score for c in citations) / max(len(citations), 1),
    ) if citations else 0.4

    latency_ms = int((time.monotonic() - t0) * 1000)

    return QueryResponse(
        answer=answer,
        citations=citations,
        agent=agent,
        iq_layers=req.iq_layers or iq_layers,
        confidence=round(confidence, 3),
        tokens_used=tokens,
        latency_ms=latency_ms,
    )


# ── Research ──────────────────────────────────────────────────────────────────

@app.post("/api/research", response_model=ResearchResponse, tags=["Research"])
async def research_endpoint(req: ResearchRequest) -> ResearchResponse:
    """
    Customer research endpoint.

    Combines Bing web search results with IQ corpus retrieval to generate
    a structured opportunity assessment for a target company.
    """
    t0 = time.monotonic()
    settings = get_settings()

    # 1 — Bing search: company context
    bing_query = f"{req.company} Azure AI analytics cloud strategy"
    if req.industry:
        bing_query += f" {req.industry}"
    web_citations = await _bing_search(bing_query, count=5)

    # 2 — AI Search: IQ opportunity context
    iq_query = f"IQ opportunities {req.industry or 'enterprise'} {' '.join(req.focus_areas or [])}"
    iq_results = await _search_index(iq_query, top=settings.search_top_k)
    iq_citations = _results_to_citations(iq_results)

    all_citations = web_citations + iq_citations

    # 3 — Synthesise with LLM
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

    # 4 — Parse LLM response (graceful fallback)
    summary = raw_answer
    opportunities: list[IQOpportunity] = []
    recommended_approach = "Engage IQ specialist for detailed discovery."

    try:
        import json
        parsed = json.loads(raw_answer)
        summary = parsed.get("summary", raw_answer)
        recommended_approach = parsed.get("recommended_approach", recommended_approach)
        for opp in parsed.get("iq_opportunities", []):
            opportunities.append(
                IQOpportunity(
                    layer=opp.get("layer", "foundry-iq"),
                    title=opp.get("title", ""),
                    description=opp.get("description", ""),
                    services=opp.get("services", []),
                    priority=opp.get("priority", "medium"),
                )
            )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Could not parse LLM JSON response for research: %s", exc)

    latency_ms = int((time.monotonic() - t0) * 1000)

    return ResearchResponse(
        company=req.company,
        industry=req.industry,
        summary=summary,
        iq_opportunities=opportunities,
        recommended_approach=recommended_approach,
        citations=all_citations,
        tokens_used=tokens,
        latency_ms=latency_ms,
    )


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
                f"/docs/search?api-version=2024-05-01-preview"
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
