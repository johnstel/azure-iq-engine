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
| **Chat/Reasoning** | GitHub Copilot SDK | $0/token via GitHub license; 6 domain skills |
| **Embeddings** | Azure OpenAI | `text-embedding-3-large` (1536-dim) |
| **Document Store** | Azure Cosmos DB (Serverless) | Corpus metadata, customer research, learning profiles |
| **Cache** | Azure Cache for Redis | Query results, embedding cache, research L1 |
| **Compute** | Azure Container Apps | FastAPI API + ingestion workers |
| **Observability** | Application Insights + OpenTelemetry | Distributed tracing, RAG quality metrics |

**Estimated cost:** ~$220-365/month (Phase 1)

## Knowledge Corpus

Multi-source ingestion with IQ-layer taxonomy tagging:

- **Microsoft Learn** — Work IQ, Fabric IQ, Foundry IQ official documentation
- **Azure Updates** — RSS feed for GA/preview/deprecation signals
- **Tech Community** — Blog posts from Microsoft engineers
- **John Savill's Technical Training** — 1,000+ Azure video transcripts with timestamps
- **Azure Architecture Center** — Reference architectures and patterns

All content tagged by: IQ layer, Azure services, capabilities, difficulty level, target role, GA status, certification relevance.

## Copilot Skills

| Skill | Purpose |
|---|---|
| `iq-architect` | Cross-layer IQ architecture Q&A |
| `azure-navigator` | Azure service deep-dives with best practices |
| `story-weaver` | Multi-source technical narrative composition |
| `customer-researcher` | Live web research → customer outcome documents |
| `latest-updates` | What changed this week in the IQ landscape |
| `competitive-context` | Microsoft IQ vs. Databricks/AWS/GCP positioning |

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
- [ ] Phase 0: Validate Copilot SDK + provision Azure OpenAI
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
- **AI:** GitHub Copilot SDK + Azure OpenAI
- **Search:** Azure AI Search (hybrid vector + BM25 + semantic reranking)
- **Storage:** Azure Cosmos DB (Serverless) + Azure Blob Storage
- **Cache:** Azure Cache for Redis
- **IaC:** Terraform
- **CI/CD:** GitHub Actions
- **Observability:** Application Insights + OpenTelemetry

## License

Private — Microsoft internal use.
