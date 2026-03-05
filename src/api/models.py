"""
Pydantic v2 request/response models for the Azure IQ Engine API.

All models use strict typing and field-level validation.
Response models include enough context for the caller to act without
needing to re-query the API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator


# ── Shared primitives ─────────────────────────────────────────────────────────

class Citation(BaseModel):
    source_url: str = Field(..., description="Canonical URL of the source document")
    title: str = Field(..., description="Document or page title")
    relevance_score: float = Field(
        ..., ge=0.0, le=1.0, description="Semantic relevance score [0-1]"
    )
    snippet: str | None = Field(None, description="Relevant excerpt from the document")
    source_type: str | None = Field(
        None, description="Source category (e.g. microsoft-learn, azure-docs)"
    )
    iq_layer: str | None = Field(
        None, description="IQ layer this document relates to"
    )


class IQOpportunity(BaseModel):
    layer: str = Field(..., description="IQ layer (work-iq, fabric-iq, foundry-iq)")
    title: str = Field(..., description="Short opportunity title")
    description: str = Field(..., description="Why this layer is relevant for the customer")
    services: list[str] = Field(
        default_factory=list,
        description="Azure services that underpin this opportunity",
    )
    priority: str = Field(
        default="medium",
        pattern="^(high|medium|low)$",
        description="Recommended priority (high / medium / low)",
    )


# ── Query ─────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="Natural-language question to answer",
    )
    agent: str | None = Field(
        None,
        description=(
            "Target agent name. If omitted, auto-routed by keyword analysis. "
            "Valid values: iq-architect, azure-navigator, latest-updates, "
            "competitive-context, story-weaver, customer-researcher"
        ),
    )
    iq_layers: list[str] | None = Field(
        None,
        description="Restrict search to specific IQ layers",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of search chunks to ground the answer with",
    )

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v.strip()


class QueryResponse(BaseModel):
    answer: str = Field(..., description="LLM-generated, grounded answer")
    citations: list[Citation] = Field(
        default_factory=list,
        description="Source chunks used to ground the answer",
    )
    agent: str = Field(..., description="Agent that generated the answer")
    iq_layers: list[str] = Field(
        default_factory=list,
        description="IQ layers identified in the answer",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model-estimated confidence [0-1]",
    )
    tokens_used: int = Field(..., ge=0, description="Total tokens consumed")
    latency_ms: int | None = Field(None, description="End-to-end latency in ms")


# ── Research ──────────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    company: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Customer or prospect company name",
    )
    industry: str | None = Field(
        None,
        max_length=100,
        description="Industry vertical (e.g. energy, financial-services)",
    )
    focus_areas: list[str] | None = Field(
        None,
        description="Specific topics or IQ layers to focus on",
    )

    @field_validator("company")
    @classmethod
    def company_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("company must not be blank")
        return v.strip()


class ResearchResponse(BaseModel):
    company: str
    industry: str | None = None
    summary: str = Field(..., description="Executive summary of the company")
    iq_opportunities: list[IQOpportunity] = Field(
        default_factory=list,
        description="Prioritised IQ opportunities for this customer",
    )
    recommended_approach: str = Field(
        ..., description="High-level engagement recommendation"
    )
    citations: list[Citation] = Field(default_factory=list)
    tokens_used: int = Field(default=0, ge=0)
    latency_ms: int | None = None


# ── Search ────────────────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    id: str = Field(..., description="Document chunk ID in the search index")
    title: str
    source_url: str
    snippet: str = Field(..., description="Best-matching text excerpt")
    score: float = Field(..., ge=0.0, description="Search relevance score")
    source_type: str | None = None
    iq_layer: str | None = None
    last_updated: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int = Field(..., description="Total matched documents (may exceed top)")
    top: int = Field(..., description="Requested result count")
    source_type_filter: str | None = None
    iq_layer_filter: str | None = None


# ── Sources ───────────────────────────────────────────────────────────────────

class SourceStats(BaseModel):
    source_id: str = Field(..., description="Source identifier")
    display_name: str
    document_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    last_crawl: datetime | None = None
    status: str = Field(
        default="unknown",
        pattern="^(active|idle|error|unknown)$",
    )
    url: str | None = None


class SourcesResponse(BaseModel):
    sources: list[SourceStats]
    total_documents: int
    total_chunks: int
    index_name: str


# ── Ingestion ─────────────────────────────────────────────────────────────────

class IngestRunRequest(BaseModel):
    sources: list[str] | None = Field(
        None,
        description="Source IDs to ingest. Omit to run all configured sources.",
    )
    dry_run: bool = Field(
        default=False,
        description="Simulate without writing to the search index",
    )
    force_recrawl: bool = Field(
        default=False,
        description="Re-crawl even if content fingerprint has not changed",
    )


class IngestJobStatus(BaseModel):
    job_id: str
    status: str = Field(
        ...,
        pattern="^(started|running|completed|failed|not_found)$",
    )
    sources: list[str] = Field(default_factory=list)
    dry_run: bool = False
    force_recrawl: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    documents_processed: int = Field(default=0, ge=0)
    chunks_indexed: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)


# ── Health / Info ─────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str


class InfoResponse(BaseModel):
    name: str
    version: str
    description: str
    sources: list[str]
    agents: list[str]
    iq_layers: list[str]
