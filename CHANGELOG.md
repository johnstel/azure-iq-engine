# Changelog

All notable changes to Azure IQ Engine will be documented in this file.

## [Unreleased]

### Added
- **Redis caching layer** (`src/api/cache.py`):
  - Two-tier caching: search results (TTL: 1 hour) and LLM responses (TTL: 4 hours).
  - Cache keys are SHA256 hashes of normalised query parameters (question + agent + filters).
  - `X-Cache: HIT` / `X-Cache: MISS` response header on `POST /api/query` for observability.
  - Graceful degradation — caching is disabled automatically when `REDIS_URL` is not set or Redis is unreachable; API continues to work normally.
  - Cache invalidation via `invalidate_all()` is called automatically after every successful (non-dry-run) ingestion run so stale corpus-derived responses are evicted.
- **Settings additions** (`src/api/settings.py`): `redis_url`, `cache_search_ttl` (default 3600 s), `cache_llm_ttl` (default 14400 s), and `has_redis` property.
- **Tests** (`tests/test_api/test_cache.py`, `tests/test_api/test_query_cache.py`): 23 unit and integration tests covering key generation, get/set/invalidate operations with mocked Redis, error resilience, and the `X-Cache` header on the query endpoint.

## [0.1.0] - 2026-03-04

### Added
- **Architecture:** v3.1 — Microsoft Agent Framework on Azure AI Foundry, no-auth public model
- **Ingestion Pipeline:**
  - MS Learn crawler (async, checkpoint/resume, IQ layer tagging)
  - YouTube crawler (Savill channel, transcript extraction)
  - Azure Updates crawler (RSS, incremental mode)
  - Tech Community crawler (3 blog sections, throttled)
  - Content-type-aware chunker (document/transcript/atomic strategies)
  - Embedding pipeline (batch processing, rate limiting, cost tracking)
  - AI Search indexer (dedup, upsert, retry)
  - Orchestrator (end-to-end pipeline with CLI)
- **Agent System:**
  - 6 specialist agents (iq-architect, azure-navigator, story-weaver, customer-researcher, latest-updates, competitive-context)
  - 2 multi-agent workflows (customer outcome, deep dive)
  - Function tools (search, research, outcome generation)
- **API Layer:**
  - FastAPI application with query, research, and search endpoints
  - IP-based rate limiting
  - Swagger UI at /docs
- **Web UI:** Minimal chat interface with agent selection and research mode
- **Infrastructure:** Terraform for all Azure resources (AI Search, Storage, Redis, Service Bus, Key Vault, Container Apps)
- **Documentation:** Architecture v3.1, 5 ADRs, expert reviews

### Architecture Decisions
- ADR-001: Microsoft Agent Framework on Foundry (not Copilot SDK)
- ADR-002: SHA256 content fingerprinting for deduplication
- ADR-003: Content-type-aware chunking strategies
- ADR-004: Azure AI Search Basic tier (not S1)
- ADR-005: Table Storage over Cosmos DB (public data, no auth needed)
