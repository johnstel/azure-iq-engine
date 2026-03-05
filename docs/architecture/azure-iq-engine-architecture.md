# Microsoft IQ & Azure Intelligence Engine — Architecture Plan
<!-- Filename: azure-iq-engine-architecture.md -->

**Document Version:** 3.0  
**Date:** March 4, 2026  
**Author:** Astra (OpenClaw)  
**Status:** DRAFT — Enriched by 3 Expert Reviews (eLearning, Business Strategy, Technical Architecture)  
**Working Name:** `azure-iq-engine`  
**Changelog:** v3.0 — Major enrichment: ModelClient abstraction (ADR-001), content-type-aware chunking, industry use case library, customer outcome doc overhaul, learning layer design, realistic cost model, resilience engineering, observability stack

---

## 1. Problem Statement

Microsoft's intelligence strategy now rests on three architectural pillars — **Work IQ**, **Fabric IQ**, and **Foundry IQ** — announced at Ignite 2025 and rapidly moving to GA in Q1 2026. These sit atop the full Azure product ecosystem (AI Search, Cosmos DB, Fabric, Foundry, Entra, Copilot Studio, Agent 365, and more). The challenge:

1. **No unified knowledge application** connects the IQ layers to the broader Azure service map in a way that enables real technical storytelling
2. **Practitioners can't ask questions** that span the full stack — e.g., "How does Fabric IQ's ontology feed into a Foundry IQ agent that uses Azure AI Search, and how does Work IQ personalize the result?"
3. **Customer engagements** require mapping a customer's industry and challenges to specific IQ capabilities + Azure services, grounded in real technical depth — not marketing slides
4. **Content is scattered** across Microsoft Learn, Tech Community blogs, Ignite sessions, Azure update feeds, and expert YouTube channels (Savill, etc.) with no unified retrieval layer

This architecture defines a **Python application** that unifies Microsoft IQ and Azure knowledge into a query engine that answers technical questions, weaves end-to-end stories, and generates customer-specific outcome documents — all powered by the **GitHub Copilot SDK** for live extensibility.

---

## 2. Microsoft IQ — The Subject Matter

The engine's knowledge domain is structured around Microsoft's three IQ layers and the Azure services that underpin them.

### 2.1 Work IQ — The User-Context Layer

**What it is:** Intelligence about how work actually happens — meetings, messages, documents, collaboration patterns, workload signals.

| Component | Description | Azure Foundation |
|---|---|---|
| **Microsoft Graph signals** | Collaboration patterns, relationship maps, interaction frequency | Microsoft Graph API |
| **M365 Copilot personalization** | Context-aware AI grounded in user's work patterns | Microsoft 365 Copilot + GPT-5.2 |
| **Agent 365** | Control plane to observe, govern, secure all AI agents (MS-built or third-party) | Entra ID conditional access extended to agents |
| **Copilot Studio agents** | Low-code agent building with Work IQ grounding | Copilot Studio + Dataverse |
| **Workflow intelligence** | Detects overload, exception-handling patterns, status-chasing loops | M365 analytics signals |

**Key question it answers:** "Who does what, how, and where are the bottlenecks?"

### 2.2 Fabric IQ — The Data-Context Layer

**What it is:** Intelligence grounded in structured enterprise data. A semantic layer that injects business meaning into raw data so AI agents can reason about business reality, not just tables.

| Component | Description | Azure Foundation |
|---|---|---|
| **Ontology** (preview) | Enterprise vocabulary + semantic layer unifying meaning across domains and OneLake | Microsoft Fabric IQ workload |
| **Native graph engine** | Multi-hop reasoning across relationships (Order → Shipment → Sensor → Breach) | Fabric IQ graph |
| **Semantic models** | Business metrics, KPIs, dimensional models with governed definitions | Power BI semantic models in Fabric |
| **Data agents** (virtual analysts) | NL query over business data respecting ontology definitions | Fabric IQ data agents |
| **Autonomous operational agents** | Trigger actions based on data-driven insights | Fabric IQ + Copilot Studio |
| **OneLake** | Unified data lake — structured, semi-structured, unstructured | Microsoft Fabric |

**Key question it answers:** "What does the data say about the business, and what does it mean?"

### 2.3 Foundry IQ — The Knowledge-Context Layer

**What it is:** Intelligence grounded in knowledge and reasoning. Where models are selected, grounded in enterprise content, evaluated, secured, and managed. The reasoning engine that makes AI context-aware.

| Component | Description | Azure Foundation |
|---|---|---|
| **Agentic RAG engine** | Dynamic retrieval-augmented generation with iterative search + multi-source reasoning | Azure AI Search + Foundry IQ |
| **Permission-aware grounding** | Respects existing permissions, sensitivity labels, compliance controls | Entra ID + Purview |
| **Model catalog & management** | Select, evaluate, fine-tune, deploy foundation models | Microsoft Foundry (ex Azure AI Foundry) |
| **Agent Factory** | Pro-code environment for building highly customized agents | Foundry SDK + agent runtime |
| **Knowledge connectors** | Connect agents to M365, cloud storage, data platforms, internal repos via one entry point | Foundry IQ connectors |
| **Evaluation & safety** | Red-teaming, content safety, responsible AI guardrails | Azure AI Content Safety |

**Key question it answers:** "What do the documents, contracts, policies, and knowledge bases say — and how do we reason across them safely?"

### 2.4 How the Three Layers Compose

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER EXPERIENCE                          │
│           M365 Copilot  │  Custom Apps  │  Agent 365            │
├─────────────────────────────────────────────────────────────────┤
│                      WORK IQ (User Context)                     │
│  Collaboration signals │ Workflow patterns │ Personalization     │
├─────────────────────────────────────────────────────────────────┤
│                    FOUNDRY IQ (Knowledge Context)                │
│  Agentic RAG │ Model management │ Permission-aware grounding    │
├─────────────────────────────────────────────────────────────────┤
│                    FABRIC IQ (Data Context)                      │
│  Ontology │ Graph engine │ Semantic models │ Data agents         │
├─────────────────────────────────────────────────────────────────┤
│                    AZURE PLATFORM SERVICES                       │
│  AI Search │ Cosmos DB │ Entra │ Purview │ Key Vault │ Monitor  │
└─────────────────────────────────────────────────────────────────┘
```

**Composition example (supply chain):**
- **Fabric IQ** detects delivery anomalies in supplier metrics via ontology-grounded graph traversal
- **Foundry IQ** grounds an agent in supplier contracts, SLAs, penalty clauses via permission-aware RAG
- **Work IQ** identifies that ops teams are buried in manual exception handling (email chains, recurring meetings)
- **Result:** An agent that proactively surfaces the problem, retrieves the contract terms, and drafts an escalation — all personalized to the user's role and workflow

---

## 3. Target Capabilities

| Capability | Description |
|---|---|
| **Microsoft IQ Knowledge Base** | Deep, structured reference for Work IQ, Fabric IQ, Foundry IQ — components, services, architecture patterns, inter-layer composition |
| **Azure Product Map** | Full Azure service catalog mapped to IQ layers — which services power which IQ capabilities |
| **Expert Content Corpus** | Indexed transcripts from Savill + other technical content creators, Microsoft Learn, Tech Community, Ignite sessions |
| **Natural Language Q&A** | Ask questions that span IQ layers and Azure services; get grounded, cited, technically precise answers |
| **Technical Story Weaving** | Compose end-to-end narratives: business problem → IQ layer mapping → Azure services → architecture → implementation |
| **GitHub Copilot SDK Skills** | Live question answering, extensible skill system, multi-model routing |
| **Customer Outcome Builder** | Research a specific customer → map industry challenges to IQ capabilities → generate tailored outcome documents |

---

## 4. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                      azure-iq-engine (Python)                       │
├──────────────┬───────────────┬──────────────┬───────────────────────┤
│  Ingestion   │  Knowledge    │  Query &     │  Customer Outcome     │
│  Pipeline    │  Store        │  Story Engine│  Builder              │
├──────────────┼───────────────┼──────────────┼───────────────────────┤
│ Multi-Source │ Azure AI      │ GitHub       │ Copilot SDK           │
│ Crawlers:    │ Search        │ Copilot SDK  │ Skills +              │
│ • MS Learn   │ (vectors +   │ (Sessions,   │ Web Research           │
│ • Tech Comm  │  hybrid)     │  Skills,     │ Agent                 │
│ • YouTube    │ CosmosDB     │  Multi-Model)│                       │
│ • Azure Feed │ (documents)  │              │                       │
│ • Ignite     │              │              │                       │
└──────────────┴───────────────┴──────────────┴───────────────────────┘
         │              │              │                │
    ┌────▼────┐   ┌─────▼─────┐  ┌────▼─────┐   ┌─────▼──────┐
    │Sources  │   │Azure AI   │  │GitHub    │   │Bing/Web    │
    │(see 5.1)│   │Search     │  │Copilot   │   │Search API  │
    │         │   │CosmosDB   │  │Platform  │   │            │
    └─────────┘   └───────────┘  └──────────┘   └────────────┘
```

---

## 5. Critical Architecture Decisions (ADRs)

> **These ADRs address existential risks identified during expert review. They must be resolved before build begins.**

### ADR-001: Agent Platform — Microsoft Agent Framework on Azure AI Foundry

**Status:** ACCEPTED — Replaces Copilot SDK (v2.0) entirely  
**Context:** Copilot SDK requires local CLI installation and is designed for developer workstations, not server-side deployments. Azure AI Foundry with Microsoft Agent Framework (RC, successor to Semantic Kernel + AutoGen) is the correct platform for a server-deployed agentic application.  
**Decision:** Use **Microsoft Agent Framework** (`pip install agent-framework --pre`) with **Azure AI Foundry** as the AI backend:
- **Agent runtime:** Agent Framework provides agent creation, function tools, multi-agent orchestration (sequential, concurrent, handoff, group chat), MCP support, streaming, checkpointing
- **LLM inference:** Azure OpenAI via Foundry-provisioned endpoints (GPT-4.1 for reasoning, GPT-4o-mini for routing)
- **Embeddings:** Azure OpenAI `text-embedding-3-large` (3072-dim)
- **Auth:** `DefaultAzureCredential` (managed identity in production)
- **Interop:** A2A (Agent-to-Agent), AG-UI, MCP (Model Context Protocol)

```python
# src/engine/agents.py — Microsoft Agent Framework
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import DefaultAzureCredential

client = AzureOpenAIResponsesClient(
    credential=DefaultAzureCredential(),
    endpoint="https://<foundry-resource>.openai.azure.com/openai/v1"
)

# IQ Architect agent — cross-layer reasoning
iq_architect = client.as_agent(
    name="iq-architect",
    instructions="You are an expert on Microsoft IQ layers (Work IQ, Fabric IQ, Foundry IQ)...",
    tools=[search_iq_corpus, get_azure_service_details, get_latest_updates],
)

# Customer Researcher agent — web research + outcome generation
customer_researcher = client.as_agent(
    name="customer-researcher",
    instructions="You research customer companies and generate IQ outcome documents...",
    tools=[bing_search, search_iq_corpus, generate_outcome_doc],
)

# Multi-agent workflow: research → architect → story weave
from agent_framework.orchestrations import SequentialBuilder
workflow = SequentialBuilder(
    participants=[customer_researcher, iq_architect, story_weaver]
).build()
```

**Consequence:** Full Azure-native deployment with managed identity auth. No local CLI dependency. Horizontal scaling via Container Apps. Server-side multi-agent orchestration with built-in patterns. Cost: Azure OpenAI token usage (~$20-65/month at expected volume).  
**Risk if ignored:** N/A — this replaces the Copilot SDK risk entirely.

### ADR-002: Ingestion Pipeline Robustness

**Status:** ACCEPTED — Must implement before first index  
**Decision:** Three mandatory pipeline features:
1. **SHA256 fingerprinting** — `SHA256(source_url + content)` per chunk; skip duplicates on re-crawl
2. **Checkpoint/resume** — Ingestion state machine in Cosmos DB; resume from `last_checkpoint` on failure
3. **Content diffing** — Compare hash before re-embedding; only re-embed changed chunks (saves 70–90% on weekly re-crawl)

**Risk if ignored:** 🔴 CRITICAL — Without fingerprinting, every re-crawl silently doubles the corpus. Without checkpoint/resume, a failure at chunk 45K of 100K restarts from zero.

### ADR-003: Content-Type-Aware Chunking

**Status:** ACCEPTED — Replace universal 512/128 chunker  
**Decision:** Different content types require different chunking strategies:

| Content Type | Strategy | Token Size | Overlap |
|---|---|---|---|
| MS Learn docs (structured) | Semantic section boundaries | 800–1200 | 128 |
| YouTube transcripts (spoken) | Sentence-boundary | 256–384 | 64 |
| Azure Updates (short posts) | Atomic (no chunking) | Full post | N/A |
| Architecture patterns (long-form) | Larger chunks for narrative coherence | 1000–1500 | 200 |
| Code samples | Function/class boundary splitting | Variable | None |

Phase 2 addition: **parent-child chunking** — small child chunks (256 tok) for vector search precision, parent chunks (1024 tok) returned to LLM for context richness. Empirically improves RAG quality 15–30%.

### ADR-004: AI Search Tier — Start on Basic

**Status:** ACCEPTED  
**Decision:** Start on Azure AI Search **Basic** (~$75/month) instead of S1 (~$250/month). Basic tier post-April 2024 supports 3 partitions, vector search, and up to 15 GB storage. At 100K chunks with 3072-dim vectors: ~1200 MB vectors + ~200 MB text/metadata = ~1400 MB. Well within Basic limits.  
**Upgrade trigger:** Partition utilization >80% OR query P99 >500ms → upgrade to S1.  
**Savings:** ~$175/month in Phase 1.

### ADR-005: Deployment Strategy

**Status:** ACCEPTED  
**Decision:** Container Apps revision-based traffic splitting:
1. Deploy new revision at 0% traffic
2. Validate via health probes + integration tests
3. Shift to 10% canary → monitor 30 min → 100%
4. Keep previous revision active 24 hours for instant rollback

---

## 6. Component Design

### 6.1 Ingestion Pipeline — Multi-Source Knowledge Corpus

The engine ingests from **multiple authoritative sources**, not just one. The knowledge domain is Microsoft IQ + the Azure ecosystem.

#### 5.1.1 Source Registry

| Source | Content | Method | Update Frequency | Priority |
|---|---|---|---|---|
| **Microsoft Learn** | Work IQ, Fabric IQ, Foundry IQ official docs; Azure service docs | Web scrape + Learn API | Weekly | **P0** — Authoritative |
| **Microsoft Tech Community** | IQ deep dives, architecture blogs, product team posts | RSS + web scrape | Weekly | **P0** — First-party |
| **Microsoft Official Blog** | Satya/exec announcements, Frontier Transformation posts | RSS + web scrape | Weekly | **P0** — Strategic |
| **Azure Updates Feed** | New services, GA/preview flags, deprecations | RSS (azure.microsoft.com/updates) | Daily | **P0** — Currency |
| **Microsoft Foundry Docs** | Agent Factory, Foundry IQ, model catalog, evaluation | Learn API | Weekly | **P0** — Core domain |
| **Ignite / Build Sessions** | Recorded sessions with transcripts | YouTube API + session catalog | Post-event | **P1** — Deep context |
| **John Savill's YouTube** | 1,000+ Azure/AI technical training videos | YouTube Data API v3 | Daily (delta) | **P1** — Expert explanation |
| **Azure Architecture Center** | Reference architectures, best practices, patterns | Web scrape | Monthly | **P1** — Patterns |
| **GitHub Repos** | Savill whiteboards, Microsoft sample repos, Copilot SDK examples | GitHub API | Weekly | **P2** — Code samples |
| **Fabric IQ Docs** | Ontology, graph engine, data agents, semantic models | Learn API | Weekly | **P0** — Core domain |

#### 5.1.2 Ingestion Flow

```
Source → Fetch → Extract (HTML→MD / Transcript) → Chunk (512 tok, 128 overlap)
  → Classify (topic tags + IQ layer mapping + Azure service tags)
  → Embed (text-embedding-3-large, 3072-dim)
  → Index (Azure AI Search) + Store (Cosmos DB)
```

#### 5.1.3 Topic Taxonomy

Every chunk is tagged with:

**IQ Layer Tags:**
- `work-iq`, `fabric-iq`, `foundry-iq`, `cross-iq` (spans multiple layers)

**Azure Service Tags:**
- `azure-ai-search`, `azure-cosmos-db`, `azure-fabric`, `azure-foundry`, `azure-entra`, `azure-purview`, `azure-monitor`, `copilot-studio`, `agent-365`, `azure-openai`, `azure-container-apps`, `azure-functions`, `azure-key-vault`, etc.

**Capability Tags:**
- `ontology`, `semantic-model`, `graph-engine`, `data-agents`, `agentic-rag`, `model-management`, `agent-factory`, `permission-grounding`, `workflow-intelligence`, `collaboration-signals`, etc.

**Content Type Tags:**
- `official-docs`, `blog-post`, `video-transcript`, `architecture-pattern`, `announcement`, `code-sample`, `ignite-session`

**Recency Weighting:**
- Content after Ignite 2025 (Nov 2025) gets boosted relevance
- Azure Updates tagged with GA/preview/deprecated status

#### 5.1.4 YouTube — Savill & Other Expert Channels

- **Channel:** John Savill's Technical Training (`UCpIn7ox7j7bH_OFj7tYouOQ`)
- **Catalog extraction:** YouTube Data API v3 — paginated `search.list` + `videos.list`
- **Transcript extraction:** `youtube-transcript-api` (primary), Whisper (fallback)
- **Timestamps preserved:** Every transcript chunk links back to `MM:SS` in the video
- **Extensible:** Add other expert channels later (e.g., Azure Friday, John Savill's Azure Master Class playlist specifically)
- **Delta detection:** Daily check for new uploads (~3-5/week for Savill)

### 5.2 Knowledge Store

#### 5.2.1 Azure AI Search — Vector + Hybrid Index

**Index schema:**

| Field | Type | Purpose |
|---|---|---|
| `chunk_id` | string (key) | Unique identifier |
| `source_type` | string | `ms-learn` / `tech-community` / `blog` / `video-transcript` / `azure-update` / `architecture` / `code-sample` |
| `source_url` | string | Original URL (or video URL with timestamp) |
| `title` | string | Document/video title |
| `published_at` | datetime | Publication date |
| `content` | string | Chunk text |
| `iq_layers` | string[] | `work-iq`, `fabric-iq`, `foundry-iq` |
| `azure_services` | string[] | Azure service tags |
| `capabilities` | string[] | Capability tags |
| `entities` | string[] | Extracted product/service names |
| `video_id` | string (nullable) | YouTube video ID if applicable |
| `video_timestamp` | int (nullable) | Seconds into video |
| `ga_status` | string (nullable) | `ga` / `preview` / `deprecated` for Azure services |
| `embedding` | vector (3072) | `text-embedding-3-large` (via Azure OpenAI — NOT Copilot SDK) |
| `fingerprint` | string | SHA256(source_url + content) — deduplication key |
| `parent_id` | string (nullable) | Parent chunk ID for parent-child chunking (Phase 2) |
| `quality_score` | double | Computed: source authority × recency × GA status |
| `target_roles` | string[] | `business-leader`, `it-pro`, `developer`, `data-engineer`, `solution-architect` |
| `difficulty` | string | `foundational`, `intermediate`, `advanced`, `expert` |
| `certification_tags` | string[] | `az-900`, `az-305`, `dp-600`, `ai-102`, etc. |
| `learn_lab_url` | string (nullable) | Associated MS Learn sandbox link |

**Search modes:** Hybrid (vector + BM25 keyword) with semantic reranking  
**Filters:** By IQ layer, Azure service, capability, source type, date range, GA status, target role, difficulty

**Scoring Profile (`iq-relevance`):**
- Field weights: `title` 2.5×, `capabilities` 2.0×, `azure_services` 1.5×, `content` 1.0×
- Freshness function: boost content published in last 90 days by 1.5×
- Tag boost: `authorityBoostTags` parameter for real-time authority weighting (official-docs, ignite-session boosted over blog posts)
- `quality_score` magnitude function: boost high-quality chunks

**Synonym Map (`iq-synonyms`):**
```
Foundry IQ, Azure AI Foundry, Microsoft Foundry => foundry-iq
Work IQ, M365 Copilot, Copilot for M365 => work-iq
Fabric IQ, Microsoft Fabric Intelligence => fabric-iq
Agent 365, Copilot Agents => agent-365
Agentic RAG, GraphRAG, retrieval augmented generation => rag
```

**Custom Analyzer (`azure-service-analyzer`):**
- Applied to `azure_services` and `entities` fields
- Keyword tokenizer + lowercase + asciifolding
- Prevents tokenization of compound names (`text-embedding-3-large` stays intact)

#### 6.2.2 Azure Table Storage — Ingestion State

Replaces Cosmos DB (v3.0) — no user state needed for public, stateless engine.

- **Ingestion state machine** — checkpoint/resume with `last_checkpoint` (ADR-002)
- **Chunk fingerprint store** — SHA256 deduplication keys
- **Anonymous query logs** (optional) — for search quality improvement, no user identity
- Partition key: `source_type` for state, `fingerprint` prefix for dedup
- **Cost:** ~$2/month vs. $40-80/month for Cosmos DB Serverless

#### 6.2.3 Azure Cache for Redis — Three-Tier Caching

| Cache Layer | TTL | Purpose | Hit Rate |
|---|---|---|---|
| **Query Result Cache** | 1 hour | `(normalized_query, filter_hash) → response` | 30-40% |
| **Embedding Cache** | 7 days | `SHA256(text) → embedding vector` | 90%+ on re-index |
| **Customer Research L1** | 24 hours | Hot customer research in front of Cosmos DB | 50%+ during active sessions |

**Service:** Azure Cache for Redis, Basic C1 (1 GB), ~$16/month. Pays for itself at >50 queries/day via avoided LLM calls.

#### 6.2.4 Azure Service Bus — Ingestion Pipeline

- **Ingestion queue:** Each crawl job publishes work items; indexer consumes and acks
- **Dead letter queue:** Failed items land in DLQ for inspection and retry
- **Basic tier:** ~$0.05/million operations — effectively free at this scale

### 6.3 Query & Story Engine — Microsoft Agent Framework on Azure AI Foundry

#### 6.3.1 Agent Setup (Azure AI Foundry + Agent Framework)

```python
# Agent runtime — Microsoft Agent Framework (RC)
# pip install agent-framework --pre
from agent_framework.azure import AzureOpenAIResponsesClient
from agent_framework.orchestrations import SequentialBuilder, ConcurrentBuilder
from azure.identity import DefaultAzureCredential

# Foundry-provisioned Azure OpenAI endpoint
client = AzureOpenAIResponsesClient(
    credential=DefaultAzureCredential(),
    endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),  # From Key Vault
)

# --- Specialist Agents ---

iq_architect = client.as_agent(
    name="iq-architect",
    instructions="""You are an expert on Microsoft's IQ layers (Work IQ, Fabric IQ, Foundry IQ).
    Answer questions that span the full IQ stack with grounded, cited responses.
    Always identify which IQ layer(s) apply and which Azure services are involved.""",
    tools=[search_iq_corpus, get_service_details, get_latest_updates],
)

azure_navigator = client.as_agent(
    name="azure-navigator",
    instructions="""You are an Azure service expert. Provide deep-dive guidance on
    specific Azure services, best practices, pricing, and Well-Architected patterns.""",
    tools=[search_iq_corpus, get_service_details],
)

story_weaver = client.as_agent(
    name="story-weaver",
    instructions="""You compose multi-source technical narratives that weave together
    IQ layers, Azure services, and real-world scenarios into compelling stories.""",
    tools=[search_iq_corpus, get_latest_updates],
)

customer_researcher = client.as_agent(
    name="customer-researcher",
    instructions="""You research customer companies via web search and generate
    IQ outcome documents with TCO/ROI modeling and competitive positioning.""",
    tools=[bing_web_search, search_iq_corpus, generate_outcome_doc],
)

latest_updates = client.as_agent(
    name="latest-updates",
    instructions="""You track what changed this week in the Microsoft IQ landscape.
    Surface GA announcements, preview features, deprecations, and pricing changes.""",
    tools=[search_iq_corpus],  # Filtered to azure-update source_type, last 7 days
)

competitive_context = client.as_agent(
    name="competitive-context",
    instructions="""You analyze Microsoft IQ capabilities vs. competing platforms
    (Databricks, AWS Bedrock, GCP Vertex, Snowflake, Salesforce Einstein).""",
    tools=[bing_web_search, search_iq_corpus],
)

# --- Multi-Agent Workflows ---

# Customer outcome: research → architect → story weave (sequential)
customer_outcome_workflow = SequentialBuilder(
    participants=[customer_researcher, iq_architect, story_weaver]
).build()

# Deep dive: architect + navigator in parallel, then story weave
deep_dive_workflow = SequentialBuilder(
    participants=[
        ConcurrentBuilder(participants=[iq_architect, azure_navigator]).build(),
        story_weaver,
    ]
).build()

# Embedding generation — Azure OpenAI directly
from openai import AsyncAzureOpenAI
embed_client = AsyncAzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    azure_ad_token_provider=DefaultAzureCredential(),
    api_version="2024-06-01"
)
```

**Why Microsoft Agent Framework on Foundry (ADR-001):**
- **Server-native:** Designed for cloud deployment, not local workstations. Scales horizontally in Container Apps.
- **Multi-agent orchestration:** Sequential, concurrent, handoff, and group chat patterns built-in with streaming.
- **Azure-native auth:** `DefaultAzureCredential` / managed identity — no PATs, no CLI processes.
- **MCP support:** Azure AI Search, Bing, GitHub as MCP tool servers.
- **A2A interop:** Agent-to-Agent protocol for future multi-service agent communication.
- **Successor to Semantic Kernel + AutoGen:** Production path to GA, Microsoft's strategic agent framework.
- **Multi-provider:** Azure OpenAI primary, but can swap to OpenAI, Anthropic, Bedrock if needed.
- Same production execution loop as Copilot CLI

#### 5.3.2 Copilot Skills — Five Domain Skills

##### Skill 1: `iq-architect`
**Purpose:** Deep expertise on the three IQ layers and how they compose.

- Answers "What is Fabric IQ's ontology?" or "How do the three IQ layers work together for supply chain optimization?"
- Understands the composition pattern: Fabric IQ (data-context) → Foundry IQ (knowledge-context) → Work IQ (user-context)
- Maps abstract IQ concepts to concrete Azure services
- Distinguishes GA vs preview capabilities
- Cites official Microsoft sources

##### Skill 2: `azure-navigator`
**Purpose:** Azure service expertise across the full platform.

- Answers questions about any Azure service (compute, data, AI, identity, networking, security, observability)
- Maps services to IQ layers — "Which Azure services power Foundry IQ?"
- Understands service composition patterns and best practices
- Covers pricing tiers, SKU selection, regional availability
- References Azure Architecture Center patterns

##### Skill 3: `story-weaver`
**Purpose:** Composes end-to-end technical narratives from retrieved knowledge.

- Takes a topic or question → retrieves across all sources → weaves a coherent story
- **Story structure:**
  1. Business problem / scenario (industry-grounded)
  2. Which IQ layers address it and how they compose
  3. Specific Azure services and architecture patterns
  4. Expert references (Savill timestamps, MS Learn links, blog posts)
  5. Implementation approach (compressed 3-week sprint)
  6. Expected outcomes with measurable metrics
- Cross-references multiple sources for depth

##### Skill 4: `customer-researcher`
**Purpose:** Research a specific customer and generate IQ-driven outcome documents.

- Web research: company profile, industry, tech stack signals, strategic priorities, recent news
- Industry → IQ mapping: which layers matter most for this customer
- Challenge inference + capability matching
- Generates structured outcome document (see §6)
- Uses Bing Web Search as MCP tool

##### Skill 5: `latest-updates`
**Purpose:** Currency layer — what's new and what changed.

- Queries Azure Updates feed for recent announcements
- Tracks IQ capability progression (preview → GA)
- Surfaces breaking changes, deprecations, new features
- Answers "What's new with Fabric IQ this month?" or "When did Foundry IQ go GA?"

#### 5.3.3 Query Flow

```
User Question
     │
     ▼
┌──────────────────┐
│ Copilot SDK       │ ← Session with 5 skills loaded
│ Session           │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     ┌────────────────────┐
│ Intent Detection  │────▶│ Route to Skill(s)  │
│ + IQ Layer ID     │     │ (single or compose)│
└──────────────────┘     └─────────┬──────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
  ┌─────────────┐         ┌──────────────┐         ┌─────────────┐
  │ Azure AI    │         │ Bing Web     │         │ Azure       │
  │ Search      │         │ Search       │         │ Updates     │
  │ (IQ + Azure │         │ (live        │         │ Feed        │
  │  + Savill)  │         │  research)   │         │             │
  └──────┬──────┘         └──────┬───────┘         └──────┬──────┘
         │                       │                        │
         └───────────────────────┼────────────────────────┘
                                 ▼
                   ┌───────────────────────┐
                   │ Response Synthesis     │
                   │ (Story Weave or        │
                   │  Direct Answer)        │
                   └───────────────────────┘
                                 │
                                 ▼
                   Cited, Grounded Response
                   with IQ layer mapping +
                   Azure service references +
                   video timestamps (when relevant)
```

---

### 6.6 Customer Outcome Builder

### 6.1 Research Pipeline

```
Customer Name
     │
     ▼
┌─────────────────┐
│ Web Research     │ → Company profile, industry, news, tech signals
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Industry Map     │ → Energy / Telecom / Finance / Healthcare / Retail / Mfg
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Challenge        │ → Infer operational pain points from public signals
│ Inference        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ IQ Capability    │ → Map challenges to Work IQ / Fabric IQ / Foundry IQ
│ Mapping          │   + specific Azure services
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Knowledge        │ → Find expert explanations (Savill, MS Learn, blogs)
│ Grounding        │   for each mapped capability
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Outcome          │ → Generate structured customer outcome document
│ Generation       │
└─────────────────┘
```

### 6.2 Output — Customer Outcome Document Template

````markdown
# [Customer Name] — Microsoft IQ Outcome Brief

## Company Profile
- Industry: [Energy / Telecom / Finance / ...]
- Scale: [employees, revenue, geography]
- Key challenges: [inferred from research]
- Current tech signals: [cloud adoption, data maturity, AI readiness]

## IQ Opportunity Map

| Business Challenge | IQ Layer | Specific Capability | Azure Service | Expected Outcome |
|---|---|---|---|---|
| Manual exception handling | Work IQ | Workflow intelligence | M365 Copilot + Agent 365 | 40% reduction in reactive work |
| Fragmented data, no shared definitions | Fabric IQ | Ontology + semantic models | Microsoft Fabric | Unified operational intelligence |
| Knowledge silos, slow contract review | Foundry IQ | Agentic RAG + permission grounding | Azure AI Search + Foundry | Secure cross-domain reasoning |
| No visibility into agent governance | Work IQ + Foundry IQ | Agent 365 control plane | Entra + Agent 365 | Unified agent observability |

## End-to-End Technical Story
[Narrative weaving the three IQ layers together for this customer's specific scenario.
Shows how data flows from Fabric IQ → Foundry IQ → Work IQ to deliver business value.]

## Architecture Pattern
[Azure service map specific to this customer — which services, how they connect,
reference architecture from Azure Architecture Center if applicable.]

## Implementation Roadmap (3-Week Sprint)
- Week 1: [Foundation — data estate, Fabric IQ ontology, initial grounding]
- Week 2: [Intelligence — Foundry IQ agent, RAG pipeline, Work IQ integration]
- Week 3: [Activation — agent deployment, Agent 365 governance, user rollout]

## Reference Material
- [Microsoft Learn links]
- [Savill video links with timestamps]
- [Architecture patterns]
- [Relevant Azure updates / GA announcements]
````

---

## 7. Azure Infrastructure

### 7.1 Resource Map (Revised — v3.0)

| Resource | SKU / Tier | Purpose | Est. Monthly Cost |
|---|---|---|---|
| Azure AI Search | **Basic** (upgrade to S1 at 80% capacity) | Vector + hybrid search for knowledge corpus | ~$75 |
| Azure Table Storage | Standard | Ingestion state machine, chunk fingerprints, anonymous query logs | ~$2 |
| Azure OpenAI | Standard S0 | Chat (GPT-4.1) + embeddings (`text-embedding-3-large`) via Foundry | ~$35-85 |
| Azure Container Apps | Consumption | Python app runtime (API + ingestion workers) | ~$35-65 |
| Azure Cache for Redis | Basic C1 (1 GB) | Query result cache, embedding cache | ~$16 |
| Azure Key Vault | Standard | API keys (Bing, YouTube) | ~$1 |
| Azure Blob Storage | Hot | Raw ingested content, cached responses, generated docs | ~$8-15 |
| Azure Service Bus | Basic | Dead letter queue for ingestion pipeline | ~$1 |
| YouTube Data API | Free tier | 10,000 units/day | $0 |
| Bing Web Search API | S1 | Customer research (1K–10K queries/month) | ~$7-25 |
| Log Analytics + App Insights | Pay-per-GB | Observability, distributed tracing, RAG metrics | ~$20-35 |

**Phase 1 estimated total:** ~$195-310/month  
**At scale (S1 upgrade, higher query volume):** ~$350-475/month

> **Cost note (v3.1):** Simplified from v3.0 by dropping Cosmos DB ($40-80/mo) in favor of Table Storage (~$2/mo). No auth layer = no user state storage overhead. All data is public — no compliance-driven audit or RBAC costs.

### 7.2 Resource Group & Naming

```
rg-iq-engine-dev
├── srch-iq-engine-dev          (Azure AI Search — Basic, upgrade to S1 at 80%)
├── st-iq-state-dev             (Table Storage — ingestion state + fingerprints)
├── oai-iq-engine-dev           (Azure OpenAI — chat + embeddings via Foundry)
├── ca-iq-engine-dev            (Container App — API)
├── ca-iq-ingest-dev            (Container App — ingestion workers)
├── redis-iq-engine-dev         (Azure Cache for Redis — Basic C1)
├── sb-iq-engine-dev            (Service Bus — ingestion DLQ)
├── kv-iq-engine-dev            (Key Vault)
├── st-iq-engine-dev            (Storage Account — Blob + raw content)
├── log-iq-engine-dev           (Log Analytics Workspace)
└── appi-iq-engine-dev          (Application Insights)
```

### 7.3 Identity & Security

- **No authentication required** — 100% public corpus, public web research, no sensitive data. Multi-user, open access.
- **Managed Identity** on Container Apps → accesses AI Search, Table Storage, Key Vault, Blob Storage, Azure OpenAI, Redis, Service Bus
- **No secrets in code** — YouTube API key, Bing API key in Key Vault
- **Azure AI Foundry auth** via `DefaultAzureCredential` (managed identity in production, Azure CLI in dev)
- **Rate limiting** — IP-based rate limiter on FastAPI to protect Azure OpenAI budget (e.g., 30 queries/min/IP)
- **Cost guardrails** — Azure Monitor budget alerts at 80%/100%/150% thresholds; Redis caching reduces LLM call volume 30-40%
- **Network:** Private endpoints to AI Search + Azure OpenAI in production (protect against data exfiltration of API keys, not user data)
- **Data classification:** All ingested content is public-domain (MS Learn, blogs, YouTube). Customer research is public Bing searches. No PII, no customer-sensitive data, no compliance requirements.
- **No user profiles, no session persistence** — each query is stateless. Optional browser-local learning state in Phase 4.

---

## 8. Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Agent Framework | Microsoft Agent Framework RC (`agent-framework`, PyPI) |
| LLM Provider | Azure OpenAI via Foundry (GPT-4.1, GPT-4o-mini) |
| Embeddings | Azure OpenAI `text-embedding-3-large` (3072-dim) |
| Multi-Agent Orchestration | Agent Framework workflows (sequential, concurrent, handoff) |
| Tool Protocol | MCP (Model Context Protocol) + native function tools |
| Agent Interop | A2A (Agent-to-Agent), AG-UI |
| Vector + Hybrid Search | Azure AI Search (semantic reranking) |
| Document Store | Azure Cosmos DB (serverless NoSQL) |
| Transcript Extraction | `youtube-transcript-api` + YouTube Data API v3 |
| Web Scraping | `httpx` + `beautifulsoup4` (MS Learn, Tech Community) |
| RSS Parsing | `feedparser` (Azure Updates, blog feeds) |
| Web Research | Bing Web Search API (MCP tool for customer research) |
| API Framework | FastAPI |
| Containerization | Docker → Azure Container Apps |
| IaC | Terraform |
| CI/CD | GitHub Actions |
| Observability | Azure Monitor + Application Insights + OpenTelemetry |

---

## 9. Project Structure

```
azure-iq-engine/
├── src/
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── ms_learn_crawler.py      # Microsoft Learn docs crawler
│   │   ├── tech_community_crawler.py # Tech Community blog crawler
│   │   ├── azure_updates_feed.py    # Azure Updates RSS ingester
│   │   ├── youtube_scraper.py       # YouTube channel catalog + transcripts
│   │   ├── architecture_center.py   # Azure Architecture Center patterns
│   │   ├── chunker.py              # Universal chunk + classify + embed
│   │   ├── indexer.py              # Push to Azure AI Search
│   │   └── scheduler.py           # Ingestion scheduling (daily/weekly)
│   ├── knowledge/
│   │   ├── __init__.py
│   │   ├── iq_taxonomy.py          # IQ layer + Azure service taxonomy
│   │   ├── search_client.py        # Azure AI Search query wrapper
│   │   └── cosmos_client.py        # Cosmos DB operations
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── main.py                 # Copilot SDK session management
│   │   ├── query_router.py         # Intent detection + skill routing
│   │   └── story_composer.py       # Multi-source narrative assembly
│   ├── customer/
│   │   ├── __init__.py
│   │   ├── researcher.py           # Web research pipeline
│   │   ├── industry_mapper.py      # Industry → IQ capability mapping
│   │   └── outcome_generator.py    # Customer outcome document generation
│   └── api/
│       ├── __init__.py
│       ├── app.py                  # FastAPI web interface
│       └── models.py              # Pydantic request/response models
├── .copilot_skills/
│   ├── iq-architect/
│   │   └── SKILL.md               # IQ layer deep expertise
│   ├── azure-navigator/
│   │   └── SKILL.md               # Full Azure service knowledge
│   ├── story-weaver/
│   │   └── SKILL.md               # End-to-end narrative composition
│   ├── customer-researcher/
│   │   └── SKILL.md               # Customer research + outcome generation
│   └── latest-updates/
│       └── SKILL.md               # Azure Updates currency layer
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── .github/
│   └── workflows/
│       ├── ingest-daily.yml        # Daily: Azure Updates + YouTube delta
│       ├── ingest-weekly.yml       # Weekly: MS Learn + Tech Community + blogs
│       └── deploy.yml              # CI/CD to Container Apps
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 10. Key Design Decisions (Updated v3.0)

| Decision | Rationale |
|---|---|
| **IQ layers as organizing principle** | Taxonomy structured around Work IQ / Fabric IQ / Foundry IQ + Azure services — survives branding evolution |
| **Multi-source corpus** | Official docs, blogs, video transcripts, update feeds — no single source dominates |
| **Microsoft Agent Framework on Foundry** | Server-native agent runtime (successor to SK + AutoGen); multi-agent orchestration, MCP, A2A, managed identity auth (ADR-001) |
| **Azure OpenAI for all inference** | Chat (GPT-4.1) + embeddings (text-embedding-3-large) via Foundry endpoints; ~$20-65/month |
| **AI Search Basic tier (not S1)** | Saves $175/month in Phase 1; upgrade trigger at 80% capacity (ADR-004) |
| **Content-type-aware chunking** | Different content types need different strategies (ADR-003) |
| **SHA256 fingerprinting + content diffing** | Prevents corpus corruption on re-crawl; saves 70-90% embedding cost (ADR-002) |
| **Industry use case library** | Pre-built IQ-to-pain-point mappings by vertical, not just routing labels |
| **Enhanced outcome docs with TCO/ROI** | Enterprise deals require financial modeling, not just technical architecture |
| **Role-based content paths** | CIO and data engineer asking the same question need fundamentally different answers |
| **3-week sprint + 3-week learning layer** | Core engine in 3 weeks; learning/engagement layer in weeks 4-6 |

---

## 11. Risks & Mitigations (Updated v3.0)

| Risk | Impact | Mitigation |
|---|---|---|
| **Agent Framework is Release Candidate** | 🟡 Medium | RC API surface is stable; GA expected weeks away. Pin version. Framework is Microsoft's strategic path (replaces SK + AutoGen). |
| **Azure OpenAI token costs** | 🟡 Medium | GPT-4.1 at ~$2/1M input tokens; at 1K queries/day ≈ $20-65/month. Redis cache reduces 30-40% of LLM calls. |
| **Ingestion corpus corruption** | 🔴 Critical | SHA256 fingerprinting + checkpoint/resume + content diffing (ADR-002) |
| **Poor retrieval quality from uniform chunking** | 🟠 High | ContentTypeAwareChunker with per-source strategies (ADR-003) |
| MS Learn content changes frequently | 🟡 Medium | Weekly re-crawl with diffing; `latest-updates` skill; content confidence scoring |
| IQ naming/branding still evolving | 🟡 Medium | Treat as architectural labels; maintain synonym maps in AI Search |
| YouTube API quota (10K units/day) | 🟡 Medium | Separate catalog fetch (API-bound) from transcript extraction (no quota — web scrape) |
| Customer research returns thin results | 🟡 Medium | Industry templates + low-confidence flagging + competitive context module |
| Cost exceeds estimate | 🟡 Medium | Start on Basic AI Search; Redis cache at 30-40% hit rate pays for itself; budget alerts |
| Enterprise customers distrust "3-week" timeline | 🟡 Medium | Separate POC scope doc (3 weeks) from enterprise roadmap (90 days → 18 months) |

---

## 12. Future Extensions (Updated v3.0)

- **Fabric IQ ontology integration:** Connect directly to a customer's Fabric IQ ontology to ground answers in their specific business model
- **Agent 365 telemetry feed:** Ingest agent performance data to answer "how is our IQ deployment performing?"
- **Copilot Studio skill export:** Package IQ skills as Copilot Studio agents for M365 deployment
- **Multi-tenant customer contexts:** Isolated sessions per customer engagement
- **Voice interface:** Ask IQ questions by voice → TTS response with references
- **MissionControl integration:** Surface IQ insights and customer outcomes in the MissionControl dashboard
- **Azure411 blog generation:** Auto-generate blog posts grounded in IQ knowledge corpus
- **Public Sector / Defense variant:** FedRAMP/GovCloud architecture with security posture documentation
- **Viva Learning connector:** Surface learning paths in M365 Teams via Microsoft Graph API
- **Knowledge graph visualization:** Interactive IQ concept map built from dependency graph
- **Parent-child chunking (Phase 2):** Small child chunks for search precision, parent chunks for LLM context
- **HyDE (Hypothetical Document Embeddings):** Query-time technique to bridge semantic gap between questions and indexed content
- **API Management:** Rate limiting, API versioning, subscription management (when multi-user)
- **Azure AI Document Intelligence:** Structured extraction from PDFs/PowerPoint (Ignite materials)

---

## 13. Resilience Engineering (v3.0)

### 14.1 Circuit Breaker Pattern

Three external dependencies require circuit breakers (using `tenacity`):

| Dependency | Max Attempts | Backoff | Timeout | Fallback |
|---|---|---|---|---|
| Azure OpenAI (chat) | 3 | Exponential 2–10s | 30s | Cached response → "service temporarily limited" |
| Azure OpenAI (embeddings) | 5 | Exponential 2–60s | 120s | Fail with retry notice |
| Azure AI Search (query) | 3 | Fixed 1s | 10s | Redis cached results → static baseline |
| Azure AI Search (index write) | 5 | Exponential 1–30s | 60s | DLQ via Service Bus |
| YouTube API | 3 | Fixed 5s | 15s | Skip, log, retry next cycle |
| Web scrape (MS Learn, blogs) | 3 | Exponential 5–30s | 20s | Skip, log, retry next cycle |

### 14.2 Health Probes

Container Apps probes on the FastAPI app:

- **`/health/live`** — process alive (always 200)
- **`/health/ready`** — validates AI Search connectivity, Cosmos DB connectivity, Redis connectivity, Azure OpenAI availability
- **`/health/started`** — startup probe with 30-attempt threshold

### 14.3 Graceful Degradation

When AI Search is unavailable:
1. Attempt AI Search (primary)
2. On failure → return cached top-N results for common queries (Redis, TTL=1hr)
3. On cache miss → curated static baseline for core IQ questions
4. Always return *something* with a degradation notice

### 14.4 Dead Letter Queue

Ingestion failures route to Azure Service Bus DLQ. Each crawl job publishes to a queue; the indexer consumes and acks. Failures land in DLQ for inspection and retry. `sb-iq-engine-dev` Basic tier (~$0.05/million ops).

---

## 14. Industry Use Case Library (v3.0)

> **Business Strategy Review finding:** The engine needs deep IQ-to-industry-pain-point mappings, not just routing labels.

### 15.1 Priority Verticals (v1)

**🔋 Energy & Utilities** *(John's domain — highest strategic relevance)*
| Scenario | IQ Layers | Azure Services | Business Outcome |
|---|---|---|---|
| Grid intelligence & asset management | Fabric IQ (ontology) + Work IQ (exceptions) | Fabric, AI Search, Event Grid | Unified asset view across siloed OT/IT systems |
| Carbon & ESG reporting | Fabric IQ (semantic models) + Foundry IQ (reasoning) | Fabric, Purview, AI Foundry | SEC climate disclosure compliance, automated Scope 1-3 |
| Predictive maintenance | Foundry IQ (agents) + Fabric IQ (telemetry) | IoT Hub, AI Foundry, Fabric | 40% reduction in unplanned downtime |
| NERC CIP compliance | Foundry IQ (permission-aware RAG) + Work IQ | Azure Arc, AI Foundry, Purview | Automated compliance evidence collection |
| Field force optimization | Work IQ (workflow intelligence) | M365, Power Platform, Teams | Inspection routing, crew scheduling, outage response |

**🏥 Healthcare & Life Sciences**
| Scenario | IQ Layers | Azure Services | Business Outcome |
|---|---|---|---|
| Clinical document intelligence | Foundry IQ (permission-aware RAG) | AI Foundry, FHIR, Purview | PHI-safe reasoning across EHRs |
| Revenue cycle automation | Fabric IQ (semantic models) + Foundry IQ | Fabric, AI Foundry | Reduce claim denial rates 25–35% |
| Regulatory submission acceleration | Foundry IQ (multi-hop RAG) | AI Foundry, AI Search | Cut FDA submission prep time 60% |

**📡 Telecom** *(MWC 2026 flagship — Microsoft already positioning)*
| Scenario | IQ Layers | Azure Services | Business Outcome |
|---|---|---|---|
| Network operations intelligence | Fabric IQ (OSS/BSS semantic layer) + Foundry IQ | Fabric, AI Foundry, Event Grid | NOC automation, mean-time-to-repair reduction |
| Customer churn prediction | Fabric IQ (data agents) + Work IQ | Fabric, M365, AI Foundry | Proactive retention, 15–20% churn reduction |
| 5G/RAN optimization | Fabric IQ (ontology) | Fabric, IoT Hub | Cross-vendor network performance unification |

**💰 Financial Services**
| Scenario | IQ Layers | Azure Services | Business Outcome |
|---|---|---|---|
| Trade surveillance | Fabric IQ (graph) + Foundry IQ (reasoning) | Fabric, AI Foundry, Purview | Anomaly detection across transaction networks |
| Regulatory intelligence | Foundry IQ (multi-hop RAG) | AI Foundry, AI Search | Real-time compliance gap identification |
| M&A due diligence | Foundry IQ (reasoning) | AI Foundry, AI Search | Intelligent data room, 50% faster DD |

### 15.2 Industry-Specific Outcome Document Templates

Each vertical gets a tailored template (not the generic v2.0 template):
- **Energy:** Regulatory compliance framing (NERC CIP, SEC ESG), grid reliability metrics, OT/IT convergence narrative
- **Healthcare:** PHI boundary enforcement, HIPAA compliance callouts, clinical workflow integration
- **Telecom:** Network KPIs (MTTR, availability), subscriber metrics, MWC/3GPP reference alignment
- **Financial Services:** Regulatory framework mapping (Basel/DORA/SEC), risk quantification, audit trail requirements

---

## 15. Customer Outcome Document — Enhanced Template (v3.0)

> **Business Strategy Review finding:** v2.0 template lacked executive summary, TCO/ROI, risk analysis, competitive positioning, and change management.

### Template Structure (v3.0)

```
1. EXECUTIVE SUMMARY (NEW — 1 page for CIO/CDO/COO)
   - Strategic positioning in customer's digital transformation
   - "Burning platform" statement — cost of inaction
   - Headline business outcomes in dollar/operational metric terms
   
2. CUSTOMER CONTEXT
   - Industry, scale, existing Azure footprint
   - AI/data maturity assessment (NEW — scored 1-5)
   - Current pain points mapped to IQ capabilities

3. IQ ARCHITECTURE RECOMMENDATION
   - Which IQ layers apply and why
   - Azure service architecture diagram
   - Data flow and integration points

4. TCO/ROI MODEL (NEW)
   - Current cost baseline (manual processes, legacy tools, data silo costs)
   - 3-year TCO for recommended IQ architecture
   - Year 1/2/3 benefit trajectory
   - NPV, payback period
   - Conservative / Base / Optimistic scenarios
   - Comparable customer benchmarks (Microsoft Customer Stories)

5. RISK ANALYSIS (NEW)
   - Technical risk: data readiness, integration complexity, model reliability
   - Organizational risk: change management, skill gaps, adoption resistance
   - Regulatory/compliance risk: data sovereignty, AI governance, audit requirements
   - Mitigation strategies per category
   
6. COMPETITIVE CONTEXT (NEW)
   - Why Microsoft IQ vs. detected alternatives (Databricks, Snowflake, AWS, GCP)
   - Competitive displacement narrative tailored to customer's existing stack

7. IMPLEMENTATION ROADMAP
   - 3-week POC sprint scope
   - 90-day production path (NEW — realistic enterprise timeline)
   - 18-month enterprise transformation horizon
   - Partner delivery model (SI engagement, FastTrack, CAF landing zones)
   
8. CHANGE MANAGEMENT (NEW)
   - Stakeholder map: who gains, who needs alignment
   - Adoption roadmap: POC → production → enterprise rollout
   - Center of Excellence design for sustainable AI operations
   - Training and enablement plan

9. REFERENCES & EVIDENCE
   - Grounded citations from knowledge corpus
   - Microsoft Customer Stories references
   - Architecture Center patterns
```

---

## 16. Learning Layer Design (v3.0)

> **eLearning Review finding:** The engine is a search tool, not a learning experience. These additions transform it into a knowledge transfer platform.

### 17.1 Core Learning Features (v1.1 — Weeks 4-6)

**Role-Based Content Paths**
- Add `target_role` field to index: `business-leader` | `it-pro` | `developer` | `data-engineer` | `solution-architect`
- Capture user role at session start; filter and rerank results accordingly
- "Explain Like I'm a [Role]" transformation — prompt engineering layer on existing skills

**Content Confidence Scoring**
- Computed at retrieval time: source authority × recency × GA status × contradiction detection
- Surfaced in every response: "This answer is based on high-confidence content (official MS Learn, published Nov 2025)."
- Low-confidence responses flagged: "⚠️ This draws on a preview-era blog post — worth verifying."

**Cognitive Load Control**
- `verbosity` parameter: `summary` (150 words) | `standard` | `detailed` (full multi-section)
- Default by role: `business-leader` → summary; `solution-architect` → detailed
- Difficulty levels on content: `foundational` | `intermediate` | `advanced` | `expert`

**Learning Session Mode** (distinct from raw query mode)
- Declared learning goal, session profile (role + existing knowledge + time budget)
- Session log in Cosmos DB — what was covered, concepts referenced, questions asked
- Session summary at end with key takeaways and next steps

### 17.2 Assessment & Validation (v1.1)

**Quiz Generation from Corpus**
- `quiz-generator` Copilot Skill: takes retrieved chunks → generates 3-5 questions at appropriate Bloom's level
- MCQ auto-graded; open-ended scored by LLM with rubric
- **Explained wrong answer pattern** (Cloud Academy-style): on miss, regenerate targeted explanation from source chunks

**Microsoft Learn Sandbox Links**
- During ingestion: enrich chunks with `learn_lab_url` when MS Learn module has associated sandbox
- Surface in responses: "This concept has a free hands-on lab: [link]"

**Certification Path Mapping**
- `certification_relevance` array field: `az-900`, `az-305`, `dp-600`, `ai-102`, `ai-900`
- When user declares cert goal, filter and sequence by exam domain weighting

### 17.3 Engagement (v1.1)

**Learning State** (browser localStorage — no server-side profiles)
- Topics covered, quiz scores, learning paths — all stored client-side
- No login required; user owns their own data
- Loss on browser clear is acceptable for a public tool
- Optional: "Export my progress" as JSON download

**Bookmark & Export**
- Pin any response in browser with label + note (localStorage)
- Export bookmarks + notes as structured markdown

**Anonymous Feedback Loop**
- Thumbs up/down per response — stored anonymously in Table Storage
- Aggregated quality signals for corpus improvement
- Weekly quality report: top 10 lowest-rated content areas

---

## 17. Observability Stack (v3.0)

> **Technical Architecture Review finding:** Application Insights alone is insufficient for a RAG system.

### 18.1 Distributed Tracing

OpenTelemetry instrumentation across all pipeline stages: fetch → chunk → embed → index → query → synthesize. End-to-end trace IDs propagate. Every slow or failed stage visible in Application Insights transaction search.

### 18.2 RAG-Specific Metrics

| Metric | Alert Threshold |
|---|---|
| `rag.retrieval.latency_p99` | > 500ms |
| `rag.retrieval.chunks_returned` (avg) | < 3 (sparse results) |
| `rag.retrieval.top_score` | < 0.7 (low relevance) |
| `rag.embedding.latency_p95` | > 2s |
| `rag.answer.latency_p99` | > 15s |
| `rag.corpus.chunk_count` | Monitor growth |
| `rag.corpus.freshness_p50` | > 30 days (stale) |
| `rag.ingestion.job_duration` | > 2× baseline |

### 18.3 Golden Test Suite

50+ query/expected-source pairs. Run post-ingestion. Alert if NDCG@5 drops below 0.7. This catches retrieval quality regressions from chunking strategy changes, index schema updates, or corpus corruption.

### 18.4 Cost Tracking

Azure Monitor Cost Management alerts:
- 80% of monthly budget (~$200) → warning
- 100% of budget (~$280) → alert
- 150% of budget (~$420) → investigation required

Per-service cost dashboard: AI Search, Cosmos DB, Container Apps, OpenAI, Redis.

---

## 18. Revised Implementation Roadmap (v3.0)

### Phase 0 — Validation (Before Build — Day 0)
- [ ] **Provision Azure OpenAI** via Foundry with GPT-4.1 + text-embedding-3-large deployments
- [ ] **Validate Agent Framework RC:** `pip install agent-framework --pre` → create test agent with function tool
- [ ] **Define retry policy matrix** for all I/O boundaries
- [ ] **Provision AI Search Basic** (not S1 — save $175/month)

### Phase 1 — Knowledge Foundation (Week 1)
- [ ] Terraform: deploy AI Search (Basic), Cosmos DB, Key Vault, Storage, Container Apps, **Azure OpenAI, Redis, Service Bus**
- [ ] Build **ContentTypeAwareChunker** (not universal 512/128)
- [ ] Build MS Learn crawler with **checkpoint/resume**
- [ ] Build YouTube scraper with **SHA256 fingerprint deduplication**
- [ ] Build Azure Updates RSS ingester (atomic chunks, no splitting)
- [ ] **Content diffing** on re-crawl — only re-embed changed chunks
- [ ] Embedding generation via Azure OpenAI + **parallel async pipeline** (20 concurrent)
- [ ] Azure AI Search indexing with **scoring profiles, synonym maps, custom analyzer**
- [ ] **OpenTelemetry instrumentation** across all ingestion stages
- [ ] Cosmos DB document storage + ingestion state machine
- **Deliverable:** Searchable knowledge corpus with deduplication, content-type-aware chunking, and full observability

### Phase 2 — Agent Framework Engine (Week 2)
- [ ] Install `agent-framework --pre` + configure Azure OpenAI via Foundry endpoint
- [ ] Build 6 specialist agents with function tools (iq-architect, azure-navigator, story-weaver, customer-researcher, latest-updates, competitive-context)
- [ ] Wire Azure AI Search as MCP tool with **scoring profiles**
- [ ] Build multi-agent workflows: customer outcome (sequential), deep dive (parallel → weave)
- [ ] Implement query router with IQ-layer-aware intent detection + **role-based filtering**
- [ ] **Redis caching** — query results (TTL=1hr), embedding cache (TTL=7d)
- [ ] **Circuit breaker** on Azure OpenAI calls (tenacity)
- [ ] CLI interface for testing queries
- [ ] **Content confidence scoring** in every response
- **Deliverable:** Working multi-agent Q&A + story engine with role-aware responses, confidence scoring, caching, and orchestrated workflows

### Phase 3 — Customer Outcomes + Production (Week 3)
- [ ] Build customer research pipeline (Bing API)
- [ ] **Industry use case library** — pre-built IQ-to-pain-point mappings for energy, healthcare, telecom, finance
- [ ] **Enhanced customer outcome generator** — v3.0 template with exec summary, TCO/ROI, risk analysis, competitive context
- [ ] **Separate output types:** POC scope doc vs. enterprise roadmap vs. pre-call brief
- [ ] FastAPI web interface with **health probes** (`/health/live`, `/health/ready`, `/health/started`)
- [ ] Docker container + Container Apps deployment with **revision-based canary release**
- [ ] GitHub Actions CI/CD + ingestion crons
- [ ] Application Insights + **golden test suite** (50+ queries)
- [ ] **Cost tracking dashboard** + budget alerts
- [ ] **Audit logging** — structured logs for customer research queries
- **Deliverable:** Production deployment with industry-specific outcome documents, resilient infrastructure, and full observability

### Phase 4 — Learning Layer (Weeks 4-6, Post-Launch)
- [ ] Learning Session mode + Learning Profile in Cosmos DB
- [ ] Role-based session initiation + `target_role` index field
- [ ] Difficulty levels + content confidence scoring in retrieval
- [ ] "Explain Like I'm a [Role]" transformation
- [ ] Quiz generation skill + explained wrong answer pattern
- [ ] Microsoft Learn sandbox link enrichment
- [ ] Certification path mapping
- [ ] Bookmark & annotate API
- [ ] User feedback loop
- [ ] Multi-language response output (Azure AI Translator)
- [ ] Curated Expert Collections
- [ ] Learning analytics workbook
- **Deliverable:** Knowledge transfer platform with assessments, personalized learning paths, and engagement tracking

---

## 19. References

### Microsoft IQ — Official
- [Microsoft Foundry Product Page](https://azure.microsoft.com/en-us/products/ai-foundry)
- [Foundry IQ — Build and Scale AI Agents](https://azure.microsoft.com/en-us/blog/microsoft-foundry-scale-innovation-on-a-modular-interoperable-and-secure-agent-stack/)
- [Fabric IQ — Semantic Foundation for Enterprise AI](https://blog.fabric.microsoft.com/en-us/blog/introducing-fabric-iq-the-semantic-foundation-for-enterprise-ai)
- [Fabric IQ — From Data Platform to Intelligence Platform](https://blog.fabric.microsoft.com/en-us/blog/from-data-platform-to-intelligence-platform-introducing-microsoft-fabric-iq)
- [Fabric IQ Overview — Microsoft Learn](https://learn.microsoft.com/en-us/fabric/iq/overview)
- [Fabric IQ Ontology — Microsoft Learn](https://learn.microsoft.com/en-us/fabric/iq/ontology/overview)
- [Frontier Transformation — Microsoft Official Blog](https://blogs.microsoft.com/blog/2026/01/27/how-microsoft-is-empowering-frontier-transformation-with-intelligence-trust/)
- [Ignite 2025: Copilot and Agents — M365 Blog](https://www.microsoft.com/en-us/microsoft-365/blog/2025/11/18/microsoft-ignite-2025-copilot-and-agents-built-to-power-the-frontier-firm/)
- [MWC 2026: Microsoft IQ for Telecoms](https://www.microsoft.com/en-us/industry/blog/telecommunications/2026/02/24/microsoft-accelerates-telecom-return-on-intelligence-with-a-unified-trusted-ai-platform/)

### Microsoft IQ — Analysis
- [Making Sense of Microsoft's AI Strategy — James Serra](https://www.jamesserra.com/archive/2026/02/making-sense-of-microsofts-ai-strategy-work-iq-fabric-iq-foundry-iq/)
- [Microsoft Debuts Work IQ, Fabric IQ, Foundry IQ — Cloud Wars](https://cloudwars.com/ai/microsoft-debuts-work-iq-fabric-iq-and-foundry-iq-a-unified-intelligence-layer-for-the-ai-powered-enterprise/)
- [Ignite Day One: Work IQ, Agent 365 — Synozur](https://www.synozur.com/post/ignite-day-one-work-iq-agent-365-and-the-next-wave-of-copilot)

### GitHub Copilot SDK
- [Building Agents with Copilot SDK — MS Tech Community](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/building-agents-with-github-copilot-sdk-a-practical-guide-to-automated-tech-upda/4488948)
- [Copilot SDK + Skill Server on Kubernetes — MS Tech Community](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/building-a-dual-sidecar-pod-combining-github-copilot-sdk-with-skill-server-on-ku/4497080)
- [Agentify Your App with Copilot SDK — ML Mastery](https://machinelearningmastery.com/agentify-your-app-with-github-copilots-agentic-coding-sdk/)

### Content Sources
- [John Savill's Technical Training — YouTube](https://www.youtube.com/channel/UCpIn7ox7j7bH_OFj7tYouOQ)
- [AzAdvertizer — Savill Video Catalog](https://www.azadvertizer.net/savill.html)
- [YouTube Data API v3](https://developers.google.com/youtube/v3)
- [Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/)
