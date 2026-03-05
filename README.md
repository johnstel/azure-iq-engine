# Azure IQ Engine

**Microsoft IQ & Azure Intelligence Engine** — A Python-based knowledge application that unifies Microsoft's IQ layers (Work IQ, Fabric IQ, Foundry IQ) and Azure services into a query engine with natural language Q&A, technical story weaving, and customer outcome document generation.

## What It Does

- **Ask questions** that span the full Microsoft IQ stack: *"How does Fabric IQ's ontology feed into a Foundry IQ agent that uses Azure AI Search?"*
- **Generate customer outcome documents** with TCO/ROI modeling, risk analysis, and competitive positioning
- **Stay current** with weekly corpus updates from Microsoft Learn, Azure Updates, Tech Community, and expert video content
- **Learn** with role-based content paths, confidence scoring, quiz generation, and certification mapping

## Architecture

Built on Azure with a dual-provider AI strategy:

| Component | Service | Purpose |
|---|---|---|
| **Search** | Azure AI Search (Basic) | Hybrid vector + BM25 + semantic reranking |
| **Agent Runtime** | Microsoft Agent Framework (RC) | Multi-agent orchestration, function tools, MCP, A2A |
| **Chat/Reasoning** | Azure OpenAI via Foundry | GPT-4.1 reasoning, GPT-4o-mini routing |
| **Embeddings** | Azure OpenAI | `text-embedding-3-large` (3072-dim) |
| **State Store** | Azure Table Storage | Ingestion state, chunk fingerprints (~$2/mo) |
| **Cache** | Azure Cache for Redis | Query results, embedding cache, research L1 |
| **Compute** | Azure Container Apps | FastAPI API + ingestion workers |
| **Observability** | Application Insights + OpenTelemetry | Distributed tracing, RAG quality metrics |

**Estimated cost:** ~$195-310/month (Phase 1) — no auth, public data only

## Knowledge Corpus

Multi-source ingestion with IQ-layer taxonomy tagging:

- **Microsoft Learn** — Work IQ, Fabric IQ, Foundry IQ official documentation
- **Azure Updates** — RSS feed for GA/preview/deprecation signals
- **Tech Community** — Blog posts from Microsoft engineers
- **John Savill's Technical Training** — 1,000+ Azure video transcripts with timestamps
- **Azure Architecture Center** — Reference architectures and patterns

All content tagged by: IQ layer, Azure services, capabilities, difficulty level, target role, GA status, certification relevance.

## Specialist Agents

Built on Microsoft Agent Framework (RC) — successor to Semantic Kernel + AutoGen:

| Agent | Purpose | Key Tools |
|---|---|---|
| `iq-architect` | Cross-layer IQ architecture Q&A | search_iq_corpus, get_service_details |
| `azure-navigator` | Azure service deep-dives with best practices | search_iq_corpus, get_service_details |
| `story-weaver` | Multi-source technical narrative composition | search_iq_corpus, get_latest_updates |
| `customer-researcher` | Live web research → customer outcome documents | bing_search, generate_outcome_doc |
| `latest-updates` | What changed this week in the IQ landscape | search_iq_corpus (filtered) |
| `competitive-context` | Microsoft IQ vs. Databricks/AWS/GCP positioning | bing_search, search_iq_corpus |

**Multi-agent workflows:**
- **Customer Outcome:** researcher → architect → story weaver (sequential)
- **Deep Dive:** architect + navigator (parallel) → story weaver

## Industry Focus

Pre-built IQ-to-pain-point mappings for:

- 🔋 **Energy & Utilities** — Grid intelligence, NERC CIP compliance, predictive maintenance, ESG reporting
- 🏥 **Healthcare** — Clinical document intelligence, revenue cycle, regulatory submissions
- 📡 **Telecom** — Network operations, churn prediction, 5G/RAN optimization
- 💰 **Financial Services** — Trade surveillance, regulatory intelligence, M&A due diligence

## Project Status

**Phase:** Pre-build (Architecture v3.0 complete, expert-reviewed)

- [x] Architecture document v3.0 with 5 ADRs
- [x] eLearning expert review (35 recommendations)
- [x] Business strategy expert review (industry use cases, GTM alignment)
- [x] Technical architecture expert review (48KB, resilience, RAG, cost model)
- [ ] Phase 0: Validate Agent Framework RC + provision Azure OpenAI via Foundry
- [ ] Phase 1: Knowledge foundation (Week 1)
- [ ] Phase 2: Copilot SDK engine (Week 2)
- [ ] Phase 3: Customer outcomes + production (Week 3)
- [ ] Phase 4: Learning layer (Weeks 4-6)

## Documentation

| Document | Description |
|---|---|
| [Architecture v3.0](docs/architecture/azure-iq-engine-architecture.md) | Full architecture plan (19 sections, 8K+ words) |
| [eLearning Review](docs/reviews/azure-iq-engine-elearning-review.md) | Learning experience gaps, assessments, taxonomy |
| [Technical Review](docs/reviews/azure-iq-engine-architecture-review.md) | RAG pipeline, resilience, cost model, ADRs |

## Tech Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI + Uvicorn
- **Agent Framework:** Microsoft Agent Framework RC (`agent-framework`)
- **AI:** Azure OpenAI via Foundry (GPT-4.1, text-embedding-3-large)
- **Search:** Azure AI Search (hybrid vector + BM25 + semantic reranking)
- **Storage:** Azure Table Storage + Azure Blob Storage
- **Cache:** Azure Cache for Redis
- **IaC:** Terraform
- **CI/CD:** GitHub Actions
- **Observability:** Application Insights + OpenTelemetry

## License

Private — Microsoft internal use.
