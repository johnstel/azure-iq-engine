# Changelog

All notable changes to Azure IQ Engine will be documented in this file.

## [Unreleased]

### Added
- **Observability:** Application Insights + structured OpenTelemetry integration
  - `src/api/telemetry.py` — OpenTelemetry tracing and metrics module wired to Azure Monitor exporter
  - Custom metrics: `iq_engine.query.latency_ms`, `iq_engine.llm.tokens_used`, `iq_engine.cache.hits/misses`, `iq_engine.ingestion.documents/chunks`, `iq_engine.errors`
  - `APPLICATIONINSIGHTS_CONNECTION_STRING` env var (optional — degrades gracefully when absent)
  - Query latency and LLM token usage recorded per request in `/api/query` and `/api/research`
  - Error counters incremented on AI Search and LLM failures
  - Ingestion stats (documents + chunks) recorded after each pipeline run
- **Infrastructure:** Application Insights availability test pinging `/health` every 5 minutes from 3 Azure regions (`azurerm_application_insights_standard_web_test`)

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
