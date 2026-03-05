# Azure IQ Engine — Principal Architect Review
<!-- Filename: azure-iq-engine-architecture-review.md -->

**Review Version:** 1.0  
**Date:** March 4, 2026  
**Reviewer:** Astra (Principal Cloud Architect)  
**Document Reviewed:** `azure-iq-engine-architecture.md` v2.0  
**Status:** DRAFT — For John's Review

---

## Executive Summary

The Azure IQ Engine is a well-conceived knowledge application with a clear domain model, a sound tech stack selection, and a realistic delivery timeline. The IQ taxonomy as organizing principle is smart — it creates a durable knowledge structure that will survive Microsoft's inevitable branding evolutions.

However, the current architecture reads as a **prototype spec**, not a production system design. The gaps are largely in the operational layer: there is no resilience engineering, no caching strategy, no cost model that survives real usage, no observability beyond "Application Insights," and no defense against the failure modes that will hit within the first 30 days of operation.

This review addresses all ten areas requested, rated by severity and effort. At the end are Architecture Decision Records (ADRs) for the six most consequential decisions.

**Summary ratings by category:**

| Category | Gap Severity | Effort to Close |
|---|---|---|
| Architecture Gaps (resilience) | 🔴 Critical | Medium |
| RAG Pipeline Quality | 🟠 High | Medium |
| Search Architecture | 🟡 Medium | Low |
| Scalability & Performance | 🟠 High | High |
| Data Pipeline Robustness | 🔴 Critical | Medium |
| Security & Compliance | 🟠 High | Medium |
| Observability | 🟠 High | Low |
| Cost Model | 🟠 High | Low (analysis) |
| Alternative Approaches | 🟡 Medium | N/A (decision points) |
| Missing Infrastructure | 🟠 High | Medium |

---

## 1. Architecture Gaps — Resilience Engineering

**Severity: 🔴 Critical | Effort: Medium**

The document has a `Risks & Mitigations` section but no resilience engineering. These are not the same thing. A risk table describes what might happen. Resilience engineering describes what the system does when it does happen.

### 1.1 Missing: Circuit Breakers

The current design has three external dependencies that will degrade or fail without warning:
- Azure AI Search (vector query path)
- Cosmos DB (document retrieval)
- GitHub Copilot SDK (LLM inference — this one is the most fragile; it's in technical preview)

**What happens when the Copilot SDK goes down?**

The document notes "Azure OpenAI fallback path" as a risk mitigation, but there's no design for it. Circuit breakers need to be explicit:

```python
# Recommended: tenacity + circuit breaker pattern
from tenacity import retry, stop_after_attempt, wait_exponential, circuit_breaker

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
async def query_copilot_sdk(session, prompt):
    ...

# Circuit breaker state: CLOSED → OPEN → HALF-OPEN
# Fallback: route to Azure OpenAI direct when circuit opens
```

**Recommendation:** Implement a `ModelRouter` class that wraps both Copilot SDK and Azure OpenAI. When Copilot SDK fails N times in M seconds, auto-route to Azure OpenAI. Cost increases but availability holds.

### 1.2 Missing: Health Probes

The Container Apps deployment has no health probe specification. Azure Container Apps supports startup probes, liveness probes, and readiness probes. None are defined.

```yaml
# Required in Container Apps definition:
probes:
  - type: Liveness
    httpGet:
      path: /health/live
      port: 8000
    initialDelaySeconds: 15
    periodSeconds: 30
  - type: Readiness
    httpGet:
      path: /health/ready
      port: 8000
    initialDelaySeconds: 5
    periodSeconds: 10
  - type: Startup
    httpGet:
      path: /health/started
      port: 8000
    failureThreshold: 30
    periodSeconds: 10
```

The FastAPI app needs a `/health/ready` endpoint that validates AI Search connectivity, Cosmos DB connectivity, and Copilot SDK session availability before accepting traffic.

### 1.3 Missing: Retry Policies with Backoff

Nowhere in the design are retry policies specified for:
- Embedding generation (Azure OpenAI rate limits at scale)
- Azure AI Search write operations during ingestion
- YouTube API calls (transient 429s are routine)
- Web scraping (MS Learn returns 503 under load)

**Recommendation:** Standardize on `tenacity` across all I/O boundaries. Define a retry policy matrix:

| Operation | Max Attempts | Backoff | Timeout |
|---|---|---|---|
| Copilot SDK query | 3 | Exponential 2s–10s | 30s |
| Azure AI Search query | 3 | Fixed 1s | 10s |
| Azure AI Search index write | 5 | Exponential 1s–30s | 60s |
| Embedding generation | 5 | Exponential 2s–60s | 120s |
| YouTube API | 3 | Fixed 5s | 15s |
| Web scrape | 3 | Exponential 5s–30s | 20s |

### 1.4 Missing: Graceful Degradation

If Azure AI Search is unavailable during a query, the current design returns an error. A graceful degradation path would:

1. Attempt AI Search (primary)
2. On failure → return cached top-N results for common queries (Redis or Blob-backed)
3. On cache miss → fall back to a curated static knowledge baseline for core IQ questions
4. Always return *something* with a degradation notice rather than a hard failure

### 1.5 Missing: Blue-Green / Canary Deployment Strategy

The CI/CD definition (`deploy.yml`) is mentioned but not designed. For a production system, Container Apps supports traffic splitting natively:

```bash
az containerapp revision set-mode --mode multiple
az containerapp ingress traffic set \
  --revision-weight latest=10 stable=90  # 10% canary
```

There's no mention of traffic splitting, revision management, or rollback procedures. For a system with a 3-week sprint to production, this needs to be in the design before the deploy workflow is written.

### 1.6 Missing: Dead Letter Queue for Ingestion

The ingestion pipeline has no dead letter mechanism. When a crawler fails mid-run (partial ingest), there's no record of what succeeded and what failed. Any re-run will re-process everything from scratch.

**Recommendation:** Add Azure Service Bus with a dead letter queue to the ingestion architecture. Each crawl job publishes to a queue; the indexer consumes and acks. Failures land in DLQ for inspection and retry.

---

## 2. RAG Pipeline Quality

**Severity: 🟠 High | Effort: Medium**

The current chunking strategy is `512 tokens, 128 overlap`. That's a reasonable starting point but it's not optimized for the specific content types in this corpus.

### 2.1 Chunking Strategy by Content Type

The current architecture uses one chunking strategy for all content. This is wrong. The optimal chunk configuration differs by source:

| Content Type | Problem with 512/128 | Recommended Strategy |
|---|---|---|
| MS Learn docs (structured) | Breaks tables, code blocks mid-element | Semantic chunking preserving document sections; 800–1200 tokens |
| YouTube transcripts (spoken) | Cuts mid-sentence, loses context | Sentence-boundary chunking; smaller chunks (256–384 tokens) with larger overlap (64-token) |
| Azure Updates (short posts) | Over-chunks; updates are 100–300 tokens each | Treat each update as atomic; no chunking needed |
| Architecture patterns (long-form) | Loses narrative arc across chunks | Larger chunks (1000–1500 tokens) for narrative coherence |
| Code samples | Splits code blocks, breaks syntax | Function/class boundary splitting; never split a code block |

**Recommendation:** Replace the universal `chunker.py` with a `ContentTypeAwareChunker` that selects strategy based on `source_type` and `content_type` tags.

### 2.2 Parent-Child Chunking (Missing)

The current architecture indexes only leaf chunks. Parent-child chunking significantly improves retrieval quality:

- **Child chunks** (128–256 tokens): fine-grained retrieval units used for vector search
- **Parent chunks** (512–1024 tokens): full context units returned to the LLM after retrieval

The search finds relevant child chunks (high precision), then fetches the parent chunk (rich context). This is the approach Microsoft themselves use in Foundry IQ and the Azure AI Search semantic ranker pipeline.

```python
class ParentChildChunker:
    def chunk(self, document):
        parent_chunks = self.split_by_section(document, max_tokens=1024)
        for i, parent in enumerate(parent_chunks):
            parent_id = f"{document.id}_p{i}"
            child_chunks = self.split_by_sentence(parent, max_tokens=256)
            for j, child in enumerate(child_chunks):
                yield {
                    "chunk_id": f"{parent_id}_c{j}",
                    "parent_id": parent_id,
                    "content": child,  # indexed for vector search
                    "parent_content": parent,  # returned to LLM
                    ...
                }
```

**Impact:** Empirically, parent-child chunking improves RAG answer quality by 15–30% on technical documentation corpora. High effort but high ROI.

### 2.3 Contextual Retrieval (Anthropic-Style) — Consider for V2

Anthropic's contextual retrieval prepends a context summary to each chunk before embedding:

```
"This chunk is from a Microsoft Learn article about Fabric IQ's ontology system,
specifically explaining how semantic labels propagate across OneLake domains.
The full document covers: [document summary]."

[original chunk text follows]
```

This dramatically improves retrieval recall because the embedding encodes *where in the document* the chunk lives, not just what the chunk says. For a corpus this technical, where context matters (a sentence about "the graph engine" means different things in Fabric IQ vs Azure Cosmos DB), this is worth prototyping in Phase 2.

**Cost implication:** Requires one LLM call per chunk to generate context prefix → one-time cost at ingestion. For 100K chunks, that's ~100K tokens at roughly $0.15 per million = ~$15 one-time. Worthwhile.

### 2.4 HyDE (Hypothetical Document Embeddings) — Query-Time

At query time, before searching the index, generate a *hypothetical ideal document* that would answer the question, then use that document's embedding for search:

```python
async def hyde_search(query: str) -> list[Chunk]:
    # Step 1: Generate hypothetical answer
    hypothetical = await llm.generate(
        f"Write a detailed technical explanation of: {query}"
    )
    # Step 2: Embed the hypothetical answer (not the query)
    embedding = await embed(hypothetical)
    # Step 3: Search with hypothetical embedding
    results = await search_index(embedding)
    return results
```

HyDE is particularly effective for this corpus because user questions ("How does Fabric IQ's ontology feed into Foundry IQ agents?") are structurally different from the indexed content (technical documentation and video transcripts). The hypothetical answer bridges the semantic gap.

**Cost:** 1 LLM call per query, ~200 tokens. At $0.03/1K tokens, negligible.

### 2.5 Late Chunking — Consider for Dense Technical Docs

Late chunking (from JinaAI, now supported in several embedding models) applies chunking *after* computing attention over the full document, preserving cross-chunk context in the embeddings. This requires a compatible embedding model. `text-embedding-3-large` does not support this natively, but it's worth tracking as the space evolves.

### 2.6 Missing: Retrieval Quality Evaluation Framework

There's no mechanism to measure whether retrieval is actually working. Before going to production, implement:

```python
class RetrievalEvaluator:
    def evaluate(self, query, retrieved_chunks, relevant_docs):
        return {
            "ndcg@10": self.ndcg(retrieved_chunks, relevant_docs, k=10),
            "mrr": self.mrr(retrieved_chunks, relevant_docs),
            "hit_rate@5": self.hit_rate(retrieved_chunks, relevant_docs, k=5),
            "mean_reciprocal_rank": self.mrr(retrieved_chunks, relevant_docs)
        }
```

Build a golden test set of 50–100 question/relevant-chunk pairs before launch. Run evaluation on every chunking strategy change.

---

## 3. Search Architecture

**Severity: 🟡 Medium | Effort: Low**

### 3.1 Is S1 the Right Tier?

S1 at ~$250/month is appropriate for Phase 1. S1 supports:
- Up to 25 million documents
- Up to 3 GB per partition (1 partition in S1)
- 15 indexes

At 100K chunks × ~3072 floats × 4 bytes ≈ 1200 MB for vectors alone, plus metadata and text content, a single-partition S1 is tight but workable. Watch the partition utilization metric closely.

**Upgrade trigger:** When approaching 2 GB partition utilization *or* when query latency P99 exceeds 500ms, move to S2 (~$500/month, 12 GB/partition) or add a second partition.

### 3.2 Missing: Scoring Profiles

The current design uses semantic reranking but doesn't define scoring profiles. For this corpus, recency and authority matter:

```json
{
  "scoringProfiles": [
    {
      "name": "iq-relevance",
      "text": {
        "weights": {
          "title": 2.5,
          "content": 1.0,
          "capabilities": 2.0,
          "azure_services": 1.5
        }
      },
      "functions": [
        {
          "type": "freshness",
          "fieldName": "published_at",
          "boost": 1.5,
          "freshness": { "boostingDuration": "P90D" }
        },
        {
          "type": "tag",
          "fieldName": "source_type",
          "boost": 2.0,
          "tag": { "tagsParameter": "authorityBoostTags" }
        }
      ]
    }
  ]
}
```

The `authorityBoostTags` parameter lets the query layer pass `["official-docs", "ignite-session"]` at query time to boost first-party content over blog posts. This is critical for accuracy — you don't want a Tech Community opinion post outranking the MS Learn official documentation.

### 3.3 Missing: Synonym Maps

Microsoft's IQ terminology is evolving rapidly and has aliases. Without a synonym map, a search for "Foundry" won't match chunks tagged with "Azure AI Foundry," and "Agent 365" won't match "Copilot Agents." Define synonym maps:

```json
{
  "synonyms": [
    "Foundry IQ, Azure AI Foundry, Microsoft Foundry => foundry-iq",
    "Work IQ, M365 Copilot, Copilot for M365 => work-iq",
    "Fabric IQ, Microsoft Fabric Intelligence => fabric-iq",
    "Agent 365, Copilot Agents => agent-365",
    "Agentic RAG, GraphRAG, retrieval augmented generation => rag"
  ]
}
```

### 3.4 Missing: Custom Analyzer for Azure Service Names

Azure service names contain hyphens and numbers that standard analyzers tokenize poorly (`text-embedding-3-large` becomes `text`, `embedding`, `3`, `large`). Define a custom analyzer:

```json
{
  "analyzers": [
    {
      "name": "azure-service-analyzer",
      "@odata.type": "#Microsoft.Azure.Search.CustomAnalyzer",
      "tokenizer": "keyword",
      "tokenFilters": ["lowercase", "asciifolding"]
    }
  ]
}
```

Apply this analyzer to `azure_services` and `entities` fields.

### 3.5 Multi-Index Federation Approach

As the corpus grows, consider partitioning into three indexes rather than one:

| Index | Content | Rationale |
|---|---|---|
| `idx-iq-core` | MS Learn, official docs, Foundry/Fabric/Work IQ specs | Highest authority; small and fast |
| `idx-iq-expert` | Savill transcripts, Architecture Center, Ignite sessions | Expert context; medium size |
| `idx-iq-dynamic` | Azure Updates, blog posts, recent announcements | High-velocity content; needs freshness bias |

Fan-out queries to all three, merge results server-side, apply a unified re-ranking pass. This lets you tune each index independently and apply different scoring profiles per content category.

---

## 4. Scalability & Performance

**Severity: 🟠 High | Effort: High**

### 4.1 Bottleneck Analysis

```
Current architecture bottlenecks (in order of impact):

1. Embedding generation (single-threaded, sequential)
   → Block: Azure OpenAI rate limits (~720 RPM for text-embedding-3-large on S0)
   → At 100K chunks: ~140 minutes in a single thread

2. No query result caching
   → Every query hits AI Search + LLM
   → Repeated queries (same question, different phrasing) cost full pipeline

3. Copilot SDK session management (unknown concurrency limits)
   → Session pool size? Concurrent session limits? Not designed.

4. Cosmos DB Serverless RU spike during initial ingest
   → 100K document writes at ~10 RU each = 1M RUs in a burst
   → Serverless cap: 5,000 RU/s → 200-second burst ceiling

5. GitHub Actions ingestion workers (single runner)
   → Sequential crawl + embed + index is a 4-6 hour job
```

### 4.2 Embedding Generation — Parallelism

Replace sequential embedding with a parallel async pipeline:

```python
import asyncio
from asyncio import Semaphore

class EmbeddingPipeline:
    def __init__(self, max_concurrent=20):
        self.sem = Semaphore(max_concurrent)
        self.client = AsyncAzureOpenAI(...)
    
    async def embed_batch(self, chunks: list[str]) -> list[list[float]]:
        async def embed_one(chunk):
            async with self.sem:
                return await self.client.embeddings.create(
                    input=chunk,
                    model="text-embedding-3-large"
                )
        
        results = await asyncio.gather(*[embed_one(c) for c in chunks])
        return [r.data[0].embedding for r in results]
```

With `max_concurrent=20` and batching by Azure OpenAI's token limits, initial ingestion drops from 140 minutes to ~12 minutes.

### 4.3 Redis Cache — Three-Tier Caching Strategy

The architecture needs caching at three levels:

```
Level 1: Query Result Cache (Redis, TTL=1hr)
  → Cache: (normalized_query, filter_hash) → response
  → Hit rate: estimated 30-40% for repeated IQ questions
  → Savings: full LLM cost avoided on cache hits

Level 2: Embedding Cache (Redis, TTL=7d)
  → Cache: SHA256(text) → embedding vector
  → Critical during re-indexing: same content, no re-embed cost

Level 3: Customer Research Cache (Cosmos DB, TTL=90d)
  → Already in design — this is correct
  → Add Redis L1 in front: TTL=24hr for active research sessions
```

**Service:** Azure Cache for Redis (Basic C1, 1GB) ~$16/month.

### 4.4 Container Apps Concurrency

The design mentions "Consumption" tier but doesn't spec concurrency parameters:

```yaml
scale:
  minReplicas: 1
  maxReplicas: 10
  rules:
    - name: http-scaling
      http:
        metadata:
          concurrentRequests: "10"  # scale out at 10 concurrent requests
    - name: cpu-scaling
      custom:
        type: cpu
        metadata:
          type: Utilization
          value: "70"
```

The ingestion worker (`ca-iq-ingest-dev`) should scale to 0 when not running (event-driven, triggered by GitHub Actions or Service Bus queue) and scale up to 3 replicas during bulk ingest.

---

## 5. Data Pipeline Robustness

**Severity: 🔴 Critical | Effort: Medium**

This is the highest-risk area. The ingestion pipeline is the foundation of the entire system. If it produces bad data, everything downstream fails silently.

### 5.1 Missing: Duplicate Detection

The current design will create duplicate chunks on every re-crawl unless explicitly prevented. There is no deduplication strategy.

**Recommendation:** Compute `SHA256(source_url + chunk_text)` as a stable chunk fingerprint. Before indexing:

```python
async def deduplicate(chunk: Chunk) -> bool:
    fingerprint = sha256(f"{chunk.source_url}:{chunk.content}".encode()).hexdigest()
    existing = await cosmos_client.get_by_fingerprint(fingerprint)
    if existing and existing.published_at == chunk.published_at:
        return False  # exact duplicate, skip
    chunk.fingerprint = fingerprint
    return True  # new or updated content
```

Store fingerprints in Cosmos DB with a `fingerprints` container (partition key: `/source_type`).

### 5.2 Missing: Content Diffing

When MS Learn content updates, the current design re-indexes the entire chunk. It should:

1. Fetch the current chunk from the index
2. Compare content hashes
3. Re-embed and re-index only changed chunks

```python
async def diff_and_update(new_chunks: list[Chunk], existing_index: dict):
    for chunk in new_chunks:
        if chunk.id in existing_index:
            if existing_index[chunk.id].fingerprint == chunk.fingerprint:
                continue  # unchanged, skip
        await upsert_chunk(chunk)
```

**Impact:** Reduces weekly re-crawl embedding cost by 70–90% (most content doesn't change week-to-week).

### 5.3 Missing: Partial Ingest Tracking

The scheduler has no concept of checkpoint/resume. If a crawler fails at chunk 45,000 of 100,000, the next run restarts from 0.

**Recommendation:** Add an ingestion state machine in Cosmos DB:

```json
{
  "job_id": "ingest-2026-03-04-ms-learn",
  "source": "ms-learn",
  "status": "running",
  "pages_fetched": 234,
  "pages_total": 890,
  "chunks_indexed": 45102,
  "last_checkpoint": "https://learn.microsoft.com/en-us/fabric/iq/ontology/...",
  "started_at": "2026-03-04T02:00:00Z",
  "error": null
}
```

Resume from `last_checkpoint` on failure. This is essential for sources with large page counts (MS Learn has thousands of pages).

### 5.4 Missing: Data Quality Scoring

Not all ingested content is equal. A 2023 blog post about Azure Search (pre-AI Search rebranding) is less useful than a 2026 MS Learn article. Implement a quality score:

```python
def score_content_quality(chunk: Chunk) -> float:
    score = 1.0
    
    # Recency scoring
    age_days = (today - chunk.published_at).days
    if age_days < 90: score *= 1.5    # Ignite 2025+ content
    elif age_days < 365: score *= 1.0  # Last year
    else: score *= 0.7                 # Older content
    
    # Authority scoring
    if chunk.source_type == "official-docs": score *= 2.0
    elif chunk.source_type == "ignite-session": score *= 1.5
    elif chunk.source_type == "blog-post": score *= 1.0
    elif chunk.source_type == "video-transcript": score *= 0.9
    
    # Completeness scoring
    if len(chunk.content) < 100: score *= 0.5  # Too short, low value
    if chunk.iq_layers: score *= 1.2            # Tagged = richer
    
    return min(score, 3.0)  # Cap at 3x
```

Store `quality_score` in the index and use it in the scoring profile boost functions.

### 5.5 Missing: Schema Evolution Strategy

The index schema will change. New fields will be added (e.g., `quality_score`, `parent_id`, `language`). Azure AI Search does not support removing fields from a live index; you must rebuild.

**Recommendation:** Define an index versioning strategy from day one:

```
srch-iq-engine-dev/indexes/
  iq-knowledge-v1  (current)
  iq-knowledge-v2  (migration in progress)
```

Use index aliases (Azure AI Search supports aliases) to switch traffic from v1 to v2 after validation. Never modify a live schema in place.

### 5.6 Missing: YouTube Quota Strategy

The document acknowledges the 10K units/day YouTube API quota. What it doesn't address:
- Initial ingest of Savill's 1,000+ videos requires ~2,000 API units for catalog + transcript metadata
- Each `videos.list` batch call = 1 unit for up to 50 videos
- Transcript extraction via `youtube-transcript-api` uses *no* API quota (it's a web scrape of the auto-generated captions)

**Recommendation:** Separate the catalog fetch (API-bound) from transcript extraction (no quota). Run catalog fetch first, store all video IDs in Cosmos DB, then extract transcripts in parallel with no API quota consumption.

---

## 6. Security & Compliance

**Severity: 🟠 High | Effort: Medium**

### 6.1 Missing: RBAC on Search Results

The current design notes that all ingested content is "public-domain." This is true for Phase 1. But the Customer Research Cache (customer company profiles, inferred challenges, generated outcome documents) is sensitive internal sales intelligence.

There is no access control on who can query customer research. The customer research cache in Cosmos DB needs:

- Row-level partition isolation per customer engagement
- Role assignments: only the owning AE/CSA should retrieve their customer's cached research
- Audit log: every customer research query logged with caller identity

**Recommendation:** Use Cosmos DB's built-in TTL (already planned, 90-day) combined with a simple RBAC check in the FastAPI layer:

```python
@router.get("/customer/{customer_id}/research")
async def get_customer_research(
    customer_id: str,
    current_user: User = Depends(get_current_user)
):
    if not await check_customer_access(current_user.id, customer_id):
        raise HTTPException(403, "Access denied to customer research")
    return await cosmos_client.get_customer_research(customer_id)
```

### 6.2 Missing: Content Sensitivity Classification

The ingestion pipeline doesn't check if scraped content contains sensitive information before indexing. This is low risk for public MS Learn and YouTube content, but the architecture notes future extensions that include customer Fabric IQ ontology data and Agent 365 telemetry. Those pipelines need Azure AI Content Safety screening.

**Recommendation:** Add a content safety check gate in the ingestion pipeline, disabled by default but wired in:

```python
async def safety_gate(chunk: Chunk) -> bool:
    if chunk.source_type in ("official-docs", "video-transcript", "blog-post"):
        return True  # Public content, skip check
    # Future: customer data sources require Content Safety screening
    result = await content_safety_client.analyze_text(chunk.content)
    return result.severity < SeverityThreshold.MEDIUM
```

### 6.3 Missing: Audit Trail

There is no audit trail for:
- Who queried what (customer research is especially sensitive)
- What the system returned
- What was indexed and when

Application Insights captures *that* queries happened, but not *what* was in them or *who* asked. For a system handling customer intelligence, this is a compliance gap.

**Recommendation:** Implement structured audit logging via Log Analytics:

```python
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    audit_event = {
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": get_user_id(request),
        "query_hash": sha256(request_body).hexdigest(),  # Hash, not raw
        "endpoint": request.url.path,
        "customer_id": extract_customer_id(request),
        "response_status": response.status_code
    }
    await log_analytics.send(audit_event, table="IQEngineAudit")
```

Note: log the *hash* of queries, not the raw text, to avoid logging potentially sensitive customer-related questions.

### 6.4 Missing: Data Residency Consideration

The architecture doesn't specify the Azure region. For an energy sector use case (mentioned as future), data residency requirements can be strict. For customer research data specifically (which may include publicly-researched but commercially-sensitive information), plan for region selection before deployment, not after.

**Recommendation:** Default to `East US 2` (lowest cost, broadest service availability). Define a `data_residency` tag on the resource group from day one. This costs nothing now and matters later.

### 6.5 GitHub PAT Rotation Policy

The architecture uses a GitHub PAT for Copilot SDK access. PATs expire. There's no mention of rotation automation.

**Recommendation:** Set the PAT to 90-day expiry. Create an Azure DevOps pipeline (or GitHub Action) that alerts 14 days before expiry and auto-rotates if using a service principal with the appropriate scopes. Store the rotation timestamp in Key Vault as a secret metadata field.

---

## 7. Observability

**Severity: 🟠 High | Effort: Low**

Application Insights is a good baseline but it's not sufficient for a RAG system where the most important failure modes are invisible to standard APM: bad retrieval, low-quality answers, stale content surfacing.

### 7.1 Missing: Distributed Tracing Across the Ingestion Pipeline

The ingestion pipeline spans multiple services: crawlers → chunker → embedding generation → AI Search indexer → Cosmos DB. A failure or slowness in any stage is invisible without distributed tracing.

**Recommendation:** Use OpenTelemetry with Application Insights exporter. Instrument each ingestion stage:

```python
from opentelemetry import trace
tracer = trace.get_tracer("iq-engine.ingestion")

async def ingest_source(source: Source):
    with tracer.start_as_current_span("ingest", attributes={"source": source.name}):
        with tracer.start_as_current_span("fetch"):
            content = await fetch_content(source)
        with tracer.start_as_current_span("chunk"):
            chunks = chunker.chunk(content)
        with tracer.start_as_current_span("embed"):
            embeddings = await embed(chunks)
        with tracer.start_as_current_span("index"):
            await indexer.index(chunks, embeddings)
```

End-to-end trace IDs propagate through all stages. You can see exactly where ingestion slows or fails.

### 7.2 Missing: RAG-Specific Metrics

Standard APM measures requests, latency, errors. For RAG, you need:

| Metric | Description | Alert Threshold |
|---|---|---|
| `rag.retrieval.latency_p99` | P99 latency for AI Search query | > 500ms |
| `rag.retrieval.chunks_returned` | Average chunks returned per query | < 3 (indicates sparse results) |
| `rag.retrieval.top_score` | Highest relevance score in result set | < 0.7 (indicates low relevance) |
| `rag.embedding.latency_p95` | P95 embedding generation latency | > 2s |
| `rag.answer.latency_p99` | P99 end-to-end answer generation | > 15s |
| `rag.corpus.chunk_count` | Total chunks in index | Monitor growth |
| `rag.corpus.freshness_p50` | Median age of indexed content | > 30 days (stale corpus) |
| `rag.ingestion.job_duration` | Per-source ingestion job duration | > 2x baseline |

Define these as custom metrics in Application Insights via `TelemetryClient.track_metric()`.

### 7.3 Missing: Retrieval Relevance Monitoring (NDCG/MRR)

Production RAG systems need continuous retrieval quality monitoring. Set up a golden test suite:

```python
GOLDEN_QUERIES = [
    {
        "query": "How does Fabric IQ ontology work?",
        "expected_sources": ["learn.microsoft.com/fabric/iq/ontology"],
        "expected_tags": ["fabric-iq", "ontology"]
    },
    # 50+ test cases...
]

async def run_quality_check():
    results = {}
    for test in GOLDEN_QUERIES:
        retrieved = await search(test["query"])
        results[test["query"]] = {
            "ndcg@5": compute_ndcg(retrieved, test["expected_sources"], k=5),
            "hit_rate": any_hit(retrieved, test["expected_sources"])
        }
    
    await log_analytics.send({
        "mean_ndcg": mean(r["ndcg@5"] for r in results.values()),
        "hit_rate": mean(r["hit_rate"] for r in results.values()),
        "timestamp": datetime.utcnow()
    }, table="RAGQualityMetrics")
```

Run this check after every ingestion job. Alert if NDCG@5 drops below 0.7.

### 7.4 Missing: Cost Tracking Dashboard

There's no mention of cost tracking. Azure Monitor Cost Management alerts should be set from day 1:

- Alert at 80% of expected monthly budget (~$250)
- Alert at 100% of budget (~$310)
- Alert at 150% of budget (~$465) — investigation required

Track per-service cost in a dashboard: AI Search, Cosmos DB, Container Apps, OpenAI (embeddings), Redis (when added).

---

## 8. Cost Optimization

**Severity: 🟠 High | Effort: Low (analysis only)**

The $310–365/month estimate is **optimistic by 40–60%** under realistic usage. Here's the full cost model:

### 8.1 Revised Cost Model

| Resource | Current Estimate | Realistic Estimate | Notes |
|---|---|---|---|
| Azure AI Search S1 | $250 | $250 | Accurate for 1 partition |
| Azure Cosmos DB Serverless | $25–50 | $60–120 | Initial ingest spike; query logs at scale |
| Azure Container Apps (API) | $20–40 | $20–40 | Accurate if low-medium traffic |
| Azure Container Apps (Ingest) | Included above | $15–25 | Separate worker, runs daily/weekly |
| Azure Key Vault | $1 | $1 | Accurate |
| Azure Blob Storage | $5 | $8–15 | 100K chunks + raw content = 10–20 GB |
| Azure OpenAI (Embeddings) | $0 (via Copilot SDK?) | $15–50/month | See note below |
| Azure Cache for Redis (C1) | Not included | $16 | Needed for performance |
| Log Analytics | $10–20 | $20–35 | More data once properly instrumented |
| YouTube API | $0 | $0 | Free tier sufficient |
| Bing Search API | Not included | $7–25/month | 1K–10K queries/month for customer research |
| **Total** | **$310–365** | **$412–531** | |

### 8.2 Embedding Generation Cost — The Invisible Line Item

The document lists embeddings as `$0 (via Copilot SDK)`. This deserves scrutiny.

- `text-embedding-3-large` pricing: $0.13 per million tokens
- Initial corpus: 100K chunks × 384 avg tokens = 38.4M tokens → **$5.00 one-time**
- Weekly re-crawl (assuming 5% content change): 5K chunks re-embedded = 1.9M tokens → **$0.25/week** = **$1/month recurring**

So embedding costs are *not* a significant line item — at this scale, $5 upfront and <$1/month ongoing. The estimate of $0 is wrong but the actual impact is small.

**However:** if embeddings are routed through the Copilot SDK (using the GitHub license), that changes things. The SDK uses GitHub's models, and `text-embedding-3-large` may or may not be available through the license. This needs validation before the architecture is finalized. If it's not available, the system needs a direct Azure OpenAI endpoint — which means adding an Azure OpenAI resource to the infrastructure (Standard S0: $0 resource cost, pay-per-token).

### 8.3 Cosmos DB Serverless — Burst Risk

Cosmos DB Serverless bills per Request Unit consumed. The 90-day TTL on query logs is a cost driver that's not accounted for:

- 1,000 queries/day × 10 RU/query = 10,000 RUs/day
- 30 days = 300,000 RUs/month
- At $0.25 per million RUs: **$0.075/month** — negligible

The initial bulk ingest is the real risk: writing 100K documents at ~10 RU each = 1M RUs = $0.25. Also negligible.

The actual Cosmos DB cost driver is **cross-partition queries** on the customer research container. If queries scan multiple partitions, RU cost scales poorly. Ensure the partition key is chosen to make customer-scoped queries single-partition.

### 8.4 Cost Reduction Strategies

1. **Prune deprecated content:** Azure services that are deprecated should be removed from the index, not just tagged. This keeps the index lean and reduces AI Search partition utilization.

2. **Tier down Container Apps during off-hours:** Ingestion workers should scale to 0. The API container can scale to 0 if this is a single-user tool (John only); tolerate cold-start latency of ~15s.

3. **Cache aggressively:** Every cached LLM response is $0.01–0.15 saved. At 30–40% cache hit rate, Redis pays for itself (at $16/month) once query volume reaches ~50 queries/day.

4. **S1 vs Basic B:** If the corpus stays under 2GB and query volume is low (< 100/day), Azure AI Search Basic tier (~$73/month) is sufficient. Move to S1 when scale demands it. This alone saves ~$177/month in Phase 1.

> **Recommendation:** Start on AI Search Basic, monitor partition utilization, and upgrade to S1 at the 1.5GB mark. Estimated Phase 1 cost: **$230–280/month**.

---

## 9. Alternative Approaches

**Severity: 🟡 Medium | Effort: N/A (decision points)**

These are architectural decision points where the current choices are defensible but alternatives should be consciously evaluated.

### 9.1 PostgreSQL + pgvector vs. Azure AI Search

| Factor | Azure AI Search | PostgreSQL + pgvector |
|---|---|---|
| Setup complexity | Low (managed) | Medium (Flexible Server) |
| Hybrid search (BM25 + vector) | Native, first-class | Requires separate BM25 layer |
| Semantic reranking | Native (AI Search semantic ranker) | Not available |
| Filtering on metadata | Excellent (OData filters) | Standard SQL WHERE |
| Cost at this scale | ~$250/month (S1) | ~$80–120/month (B4ms Flexible) |
| Schema changes | Painful (requires rebuild) | Standard ALTER TABLE |
| Azure-native integration | First-class | Good (via extensions) |

**Verdict:** Azure AI Search wins for this use case. The semantic reranker alone is worth the cost premium for a RAG system — it's the difference between "retrieves relevant chunks" and "retrieves the *most* relevant chunks." Keep AI Search. If budget becomes critical, pgvector is the fallback path.

### 9.2 LangChain / LlamaIndex vs. GitHub Copilot SDK

| Factor | Copilot SDK | LangChain/LlamaIndex |
|---|---|---|
| Cost | $0/token (GitHub license) | Full LLM inference cost |
| Maturity | Technical preview (risk) | Production-mature |
| RAG tooling | Basic (via MCP tools) | Rich (LlamaIndex is built for RAG) |
| Agent framework | Copilot Skills | LangChain Agents / LlamaIndex Agents |
| Azure integration | Native | Good (Azure LLM wrappers) |
| Community/docs | Limited | Extensive |
| Debugging | Hard | Better tooling |

**Verdict:** The $0/token argument is compelling for a personal tool. For production at scale or for customer-facing deployment, LangChain + Azure OpenAI is more defensible. A clean abstraction layer around the LLM client means you can swap. **Implement the adapter pattern now; don't couple the business logic to Copilot SDK directly.**

### 9.3 Container Apps vs. Azure Functions

| Factor | Container Apps | Azure Functions |
|---|---|---|
| Long-running tasks | Native | Requires Durable Functions |
| Custom runtime | Any (Docker) | Limited runtimes |
| Scale to zero | Yes | Yes (Consumption plan) |
| Cold start | ~15s | ~2-5s |
| Ingestion workers | Better (long-running jobs) | Worse (timeout constraints) |
| API hosting | Good (FastAPI native) | Good (HTTP trigger) |

**Verdict:** Container Apps is the right choice. The ingestion workers are long-running (multi-hour for full crawls) and don't fit the Functions execution model without Durable Functions complexity.

### 9.4 Cosmos DB vs. Azure Table Storage

| Factor | Cosmos DB Serverless | Table Storage |
|---|---|---|
| Cost at low scale | ~$25–50/month | ~$1–3/month |
| Query flexibility | Rich (NoSQL, SQL API) | Key-value only |
| TTL support | Native | Not available |
| Schema flexibility | High | High |
| Consistency levels | Configurable | Eventual only |

**Verdict:** Cosmos DB is appropriate for document store + customer research cache due to TTL support and query flexibility. But consider **Azure Table Storage for the ingestion state machine and fingerprint store** — these are pure key-value lookups that don't need Cosmos DB's features. Saves ~$10/month and reduces Cosmos DB RU consumption.

---

## 10. Missing Infrastructure

**Severity: 🟠 High | Effort: Medium**

These services should be in the architecture but aren't:

### 10.1 Azure API Management — Critical for Production

Every external call to the FastAPI endpoint goes directly to Container Apps. There's no:
- Rate limiting (per user or global)
- API versioning
- Request/response transformation
- Client authentication at the edge
- Usage analytics and subscription management

**Recommendation:** Add Azure API Management (Developer tier, ~$49/month) in front of the Container Apps API. Define policies for:
- Rate limit: 60 requests/minute per user
- JWT validation for caller identity
- Request logging to Log Analytics

If budget is tight, implement rate limiting in FastAPI middleware (via `slowapi`) as a stopgap.

### 10.2 Azure Cache for Redis — High Priority

Already addressed in §4.3. This is a required addition, not optional, once query volume exceeds 20/day.

### 10.3 Azure AI Document Intelligence — Medium Priority

The ingestion pipeline uses `httpx + beautifulsoup4` for web scraping. For complex documents (PDFs from Architecture Center, PowerPoint decks from Ignite), HTML scraping misses structure.

Azure AI Document Intelligence can extract structured content from PDFs with tables, headers, and code blocks preserved. For Ignite session materials (often PDFs), this dramatically improves chunk quality.

**Cost:** $1.50 per 1,000 pages. For 500 Ignite PDFs averaging 20 pages = 10,000 pages = **$15 one-time**. Add to the ingestion pipeline as a content-type-aware extractor.

### 10.4 Azure Content Safety — Low Priority for Now, Required Later

As noted in §6.2, this becomes required when the pipeline ingests customer-sourced content. Wire it in from day one but disable for public-domain sources.

**Cost:** $0.002 per 1,000 characters. Negligible for this volume.

### 10.5 Azure Service Bus — Required for Reliable Ingestion

Already discussed in §1.6. The dead letter queue pattern requires Service Bus. Basic tier: **$0.05/million operations** — effectively free at this scale.

### 10.6 Azure Front Door vs. Direct Container Apps

For a single-region, single-user tool, Azure Front Door ($35+/month) is overkill. Skip it. If the architecture expands to multi-user or multi-region, Front Door becomes relevant.

### 10.7 Azure OpenAI Resource — May Be Required

As discussed in §8.2, the architecture needs to validate whether embedding generation is available through the Copilot SDK license. If not, an Azure OpenAI resource is required. Add it to the Terraform manifest now as a commented resource — activate if needed. Cost: $0 (resource cost) + per-token usage.

---

## Architecture Decision Records (ADRs)

### ADR-001: LLM Inference Layer

**Status:** Accepted (with condition)  
**Context:** The system uses GitHub Copilot SDK for $0/token inference via GitHub Enterprise license.  
**Decision:** Use Copilot SDK as primary, Azure OpenAI as fallback. Implement via an abstraction layer (`ModelClient` interface) that both providers implement.  
**Condition:** Validate before build that `text-embedding-3-large` is available through the Copilot SDK. If not, provision Azure OpenAI endpoint for embeddings from day one.  
**Consequence:** ~$0 inference cost at current scale. If Copilot SDK breaks (it's in preview), failover to Azure OpenAI adds ~$30–100/month at this usage level.  
**Severity if wrong:** 🔴 Critical — if SDK breaks and no fallback exists, the entire engine is offline.

---

### ADR-002: Single Index vs. Multi-Index Federation

**Status:** Proposed  
**Context:** Current design uses one Azure AI Search index. At 100K+ chunks, a single index becomes harder to tune and score independently for different content types.  
**Decision:** Start with one index (Phase 1). Migrate to three-index federation (§3.5) when corpus exceeds 50K chunks or when scoring needs diverge by content type.  
**Trigger:** Monitor partition utilization weekly. At 1.5GB or when scoring profile conflicts arise, initiate index federation.  
**Consequence:** Phase 1 is simpler. Phase 2 migration requires a full index rebuild but enables independent tuning per content category.

---

### ADR-003: Chunking Strategy

**Status:** Proposed — Replace Universal Chunker  
**Context:** Current design uses `512 tokens, 128 overlap` for all content types. This is suboptimal for structured docs, transcripts, short updates, and code samples.  
**Decision:** Implement `ContentTypeAwareChunker` as described in §2.1. For Phase 1, prioritize the transcript (Savill) and official-docs strategies. Add parent-child chunking in Phase 2.  
**Consequence:** Higher development effort in Week 1 (2–4 additional days). Higher retrieval quality from launch. Avoids a painful re-indexing cycle if chunking strategy changes post-launch.  
**Severity if skipped:** 🟠 High — poor chunking degrades every answer the system generates.

---

### ADR-004: Cosmos DB vs. Hybrid Storage

**Status:** Proposed  
**Context:** Cosmos DB is used for three distinct purposes: document store, customer research cache, and query/interaction logs. Each has different access patterns.  
**Decision:** Keep Cosmos DB for document store and customer research cache (these need TTL, rich queries, and NoSQL flexibility). Move ingestion state machine and chunk fingerprints to Azure Table Storage (key-value lookups, ~10x cheaper).  
**Consequence:** Two storage services instead of one. Adds minor operational complexity. Saves ~$10–15/month in RU consumption.

---

### ADR-005: Deployment Strategy

**Status:** Proposed  
**Context:** The current CI/CD design has no traffic splitting or rollback strategy.  
**Decision:** Use Container Apps revision management with traffic splitting. Deploy new revisions at 0% traffic, validate via health endpoints and integration tests, then shift to 10% (canary), then 100%. Keep the previous revision active for 24 hours for instant rollback.  
**Consequence:** Slightly more complex deployment pipeline. Zero-downtime deployments. Rollback in seconds (traffic shift) rather than minutes (redeploy).  
**Required for:** Any production deployment serving more than one user.

---

### ADR-006: Observability Stack

**Status:** Proposed  
**Context:** Current design relies on Application Insights alone. This is insufficient for a RAG system where the key failure modes (bad retrieval, stale content, low answer quality) are invisible to standard APM.  
**Decision:** Use Application Insights as the baseline, extend with:  
1. OpenTelemetry instrumentation across all pipeline stages  
2. Custom Log Analytics tables for RAG quality metrics (NDCG, MRR, hit rate)  
3. A golden test suite of 50+ query/expected-source pairs, run post-ingestion  
4. Cost tracking dashboard in Azure Monitor Cost Management  
**Consequence:** ~1 week of additional instrumentation work. The payoff is catching retrieval quality regressions before users do.

---

## Prioritized Action Plan

### Immediate (Before Build — Week 0)

| Action | Severity | Effort |
|---|---|---|
| Validate Copilot SDK supports `text-embedding-3-large` | 🔴 Critical | 2 hours |
| Design ModelClient abstraction (Copilot SDK + Azure OpenAI) | 🔴 Critical | 1 day |
| Define retry policy matrix for all I/O boundaries | 🔴 Critical | 4 hours |
| Add health probe endpoints to FastAPI design | 🔴 Critical | 2 hours |
| Switch AI Search to Basic tier (save $177/month) | 🟠 High | 30 minutes |

### Week 1 (Knowledge Foundation)

| Action | Severity | Effort |
|---|---|---|
| Implement ContentTypeAwareChunker | 🟠 High | 2–3 days |
| Add SHA256 fingerprint deduplication to indexer | 🔴 Critical | 4 hours |
| Add ingestion state machine (checkpoint/resume) | 🔴 Critical | 1 day |
| Define AI Search synonym maps and scoring profiles | 🟡 Medium | 4 hours |
| Add OpenTelemetry instrumentation to ingestion pipeline | 🟠 High | 1 day |

### Week 2 (Engine Build)

| Action | Severity | Effort |
|---|---|---|
| Implement circuit breaker for Copilot SDK | 🔴 Critical | 4 hours |
| Add Redis cache for query results and embeddings | 🟠 High | 1 day |
| Implement HyDE at query time | 🟠 High | 4 hours |
| Add Container Apps scaling rules | 🟠 High | 2 hours |
| Define deployment revision traffic-split strategy | 🟠 High | 4 hours |

### Week 3 (Production Hardening)

| Action | Severity | Effort |
|---|---|---|
| Implement audit logging for customer research queries | 🟠 High | 4 hours |
| Build golden test suite (50 query/source pairs) | 🟠 High | 1 day |
| Set budget alerts in Azure Cost Management | 🟡 Medium | 30 minutes |
| Add Service Bus dead letter queue for ingestion failures | 🟡 Medium | 1 day |
| Document rollback procedures for all components | 🟡 Medium | 4 hours |

---

## Final Assessment

The Azure IQ Engine has a strong foundation: the domain model is correct, the IQ taxonomy as organizing principle is sound, and the tech stack choices are largely appropriate. The 3-week sprint is realistic *if* the team is tight-focused and the architecture gaps above are addressed before building, not after.

The two areas that could kill the project if ignored:

1. **The Copilot SDK dependency** — it's in technical preview. Build the abstraction layer before writing a single line of business logic that touches the SDK directly. The entire system cannot be held hostage to a preview SDK.

2. **Ingestion pipeline robustness** — the knowledge corpus is the engine's foundation. Duplicate chunks, partial ingests, and no fingerprinting will corrupt the corpus silently and produce subtly wrong answers. Fix the pipeline before indexing anything.

Everything else is optimization. These two are existential.

---

*Review complete. Questions or challenges to any finding → bring to architecture review.*
