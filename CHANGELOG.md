# Changelog

All notable changes to Azure IQ Engine will be documented in this file.

## [Unreleased]

### Added
- **`src/ingestion/index_manager.py`**: Python module to provision the
  `iq-engine-index` on Azure AI Search using the `azure-search-documents` SDK.
  Implements the full schema from `infra/search_index.tf`:
  - 19 text/metadata fields (filterable, facetable, and sortable as defined)
  - 3072-dimension HNSW vector field (`embedding`, cosine metric)
  - Semantic configuration (`iq-semantic`): title → content → keyword fields
  - Idempotent `create_or_update_index` upsert — safe to re-run
  - CLI entry-point: `python -m src.ingestion.index_manager [--delete]`

### Fixed
- **`src/ingestion/index_manager.py`**: Vector field `_VECTOR_DIMENSIONS` corrected from 1536 → **3072** — the native default output size for `text-embedding-3-large`. The 1536-dim figure belongs to `text-embedding-ada-002`. Using the wrong dimension would cause all indexing operations to fail with a dimension mismatch error.
- **`src/ingestion/embedder.py`**: `_EMBEDDING_DIMENSIONS` constant and all docstring references corrected 1536 → 3072.
- **`src/engine/model_client.py`**: Stale `1536-dim` comment corrected to `3072-dim`.
- **`infra/search_index.tf`**: `dimensions = 1536` corrected to **3072** and stale `text-embedding-ada-002` comment updated to `text-embedding-3-large`.

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
