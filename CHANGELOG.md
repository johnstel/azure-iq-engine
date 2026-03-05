# Changelog

All notable changes to Azure IQ Engine will be documented in this file.

## [Unreleased]

### Added
- **Ingestion Pipeline:**
  - Azure Architecture Center content source (`architecture_center`) — crawls reference architectures, patterns, and best practices from `learn.microsoft.com/en-us/azure/architecture/`. IQ layer tags derived from content keywords (cross-cutting).
  - Well-Architected Framework content source (`well_architected`) — crawls all five WAF pillars (reliability, security, cost optimization, operational excellence, performance efficiency) from `learn.microsoft.com/en-us/azure/well-architected/`. IQ layer tags derived from content keywords (cross-cutting).
  - `MSLearnCrawler.crawl_all()` method — uniform `crawl_all()` interface consistent with all other crawlers, used by the orchestrator.
  - Architecture Center and WAF URL prefixes added to the allowed crawl boundary in `MSLearnCrawler`.
  - Improved IQ layer detection: Architecture Center and WAF pages always use content-keyword fallback to tag across `fabric-iq`, `foundry-iq`, and `work-iq`.

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
