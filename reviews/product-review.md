# Azure IQ Engine — Product Review

**Reviewer:** Astra (Product/Business Perspective)  
**Date:** 2026-03-05  
**Version Tested:** 0.3.8  
**Endpoint:** https://ca-iq-engine-01.icygrass-2e1bb7f3.centralus.azurecontainerapps.io  
**Test Scope:** All documented API endpoints, content coverage across IQ layers, latency profiling, error surface

---

## Executive Summary

Azure IQ Engine is a promising concept: a unified knowledge platform that maps Microsoft's IQ layers (Work IQ, Fabric IQ, Foundry IQ) to Azure services and uses retrieval-augmented generation to help sales engineers prep for customer meetings and generate outcome-oriented narratives. The infrastructure is live and stable. The search and Q&A capabilities work and return structured, citable answers.

However, the platform's single most differentiating feature — **customer research and IQ opportunity assessment** (`/api/research`) — is completely broken with a 500 Internal Server Error on every call. Until that is fixed, this cannot be positioned as a sales-enablement or customer prep tool. Everything else is a capable but generic Azure knowledge base.

**Overall readiness: Not demo-ready for customers. Ready for internal dogfooding and iteration.**

---

## Test Results Summary

| Endpoint | Status | Notes |
|---|---|---|
| `GET /health` | ✅ 200 OK | `{"status": "healthy", "version": "0.3.8"}` |
| `GET /api/sources` | ✅ 200 OK | 2,394 chunks; 5 of 8 sources idle/empty |
| `GET /api/search?q=azure+key+vault` | ✅ 200 OK | Good results; all from ms-learn; redundant chunks |
| `POST /api/query` (network security) | ✅ 200 OK | 10.4s latency; well-structured; all IQ layers tagged |
| `POST /api/query` (Container Apps vs AKS) | ✅ 200 OK | 15.3s latency; good comparison; citations generic |
| `POST /api/research` (Duke Energy) | ❌ 500 Error | Core feature broken |
| `POST /api/research` (JPMorgan Chase) | ❌ 500 Error | Core feature broken |

---

## Category Ratings

---

### 1. Value Proposition ⭐⭐ (2/5)

**The promise:** Unify Microsoft's IQ layers with Azure services for sales engineers to prep for customer meetings and generate outcome documents.

**The reality:**
- The research/customer-prep feature (`/api/research`) — the centerpiece of the value prop — returns 500 errors for every request tested (Duke Energy/energy, JPMorgan Chase/finance).
- Without working research output, the app is a well-organized Azure docs search engine, which already exists at learn.microsoft.com.
- The IQ layer framing (Work IQ, Fabric IQ, Foundry IQ) is architecturally present in search tags (`iq_layer` field) but does not meaningfully shape Q&A answers. Every query returns `"iq_layers": ["work-iq","fabric-iq","foundry-iq"]` regardless of topic — this is a pass-through, not a routing signal.
- No customer-facing output format (slide deck, one-pager, executive brief) is surfaced through the API.

**What would make this a 4-star:** Working `/api/research` that returns a structured opportunity assessment with company-specific IQ recommendations, potential customer outcomes, and suggested Azure services — all in a format a sales engineer can hand to their account team.

---

### 2. Answer Quality ⭐⭐⭐½ (3.5/5)

**Strengths:**
- Answers are well-structured with bold headers and clear service categorization.
- Citations link to real Microsoft Learn URLs with relevance scores.
- Network security question correctly surfaces: Azure Firewall, DDoS Protection, Bastion, Private Link, NAT Gateway, Application Gateway, Sentinel — all accurate.
- Container Apps vs AKS comparison correctly distinguishes serverless abstraction vs full Kubernetes control plane, including Day-2 ops consideration.
- Agent routing appears to work: network security routed to `azure-navigator`; competitive comparison routed to `competitive-context`.
- Confidence scores are consistent (0.95 across both queries — may be hardcoded).

**Weaknesses:**
- **Latency is unacceptable for demos:** 10.4s and 15.3s response times. Showing this to a customer with a spinner running for 15 seconds would be embarrassing.
- **Citations are generic:** Both queries pulled primarily from "Azure reliability documentation" and "Azure Architecture Center" landing pages — not deep-linked to specific articles. The snippets are navigation menus, not technical content.
- **IQ layer differentiation is absent in answers:** A question about network security should ideally map to Work IQ (IT admin policy), Foundry IQ (AI-assisted threat detection), or Fabric IQ (security data pipelines) — but the answer is a flat list of services with no layer-aware narrative.
- **Confidence scores look hardcoded** at 0.95 for every query regardless of question specificity. This erodes trust in the scoring system.

---

### 3. Research Quality ⭐ (1/5)

**Both research requests failed with HTTP 500 Internal Server Error.**

This is the critical blocker. The `/api/research` endpoint is the entire product differentiator — it's what separates IQ Engine from just asking ChatGPT. Without it:
- No customer IQ opportunity assessment
- No industry-specific recommendations
- No focus area mapping (foundry_iq, fabric_iq, work_iq per customer)
- No executive-ready output

**Root cause unknown** (no error body returned — just "Internal Server Error"). Likely candidates: LLM prompt chain failure, missing company context database, or unimplemented route handler.

**Priority:** Fix this before any customer-facing use.

---

### 4. Content Coverage ⭐⭐⭐ (3/5)

**What's loaded:**

| Source | Documents | Status |
|---|---|---|
| ms-learn | 2,333 | ✅ Active |
| blog-post | 56 | ✅ Active |
| video-transcript | 5 | ✅ Active (barely) |
| microsoft-learn (alt) | 0 | 🟡 Idle |
| azure-docs | 0 | 🟡 Idle |
| azure-updates | 0 | 🟡 Idle |
| techcommunity | 0 | 🟡 Idle |
| azure411-blog | 0 | 🟡 Idle |

**IQ Layer Coverage Observed:**
- `fabric-iq`: ✅ Strong — Fabric lakehouse content (Delta Lake, medallion architecture, Spark/SQL) is present and well-tagged.
- `work-iq`: ✅ Present — Microsoft 365 Copilot hub, Microsoft Viva content indexed.
- `foundry-iq` (as `azure-core`): ⚠️ Weak — AI Foundry content is tagged `azure-core`, not `foundry-iq`. Foundry IQ is under-differentiated.

**Gaps:**
- **97% of content is ms-learn.** Blog posts (56), video transcripts (5), and the azure411-blog (0) are the sources that would provide proprietary, opinionated differentiation — they're nearly empty or inactive.
- **No azure-updates** content means no recent service announcements — a sales engineer asking about "what's new in Azure AI" would get stale answers.
- **No techcommunity content** means no community patterns, field stories, or customer proof points.
- **No `last_updated` metadata** on any content — it's impossible to know how current the indexed content is.
- **Redundant chunk deduplication needed:** Search results for "azure key vault" returned 5 results from the exact same `source_url`, just different heading anchors — reduces perceived quality.
- **`foundry-iq` layer appears largely absent** as a distinct tag. Foundry content exists but is tagged `azure-core`. The IQ layer taxonomy is not fully applied.

---

### 5. Competitive Position vs. ChatGPT/Copilot ⭐⭐½ (2.5/5)

**Honest assessment:** In its current state, Azure IQ Engine does not clearly outperform asking ChatGPT with a well-crafted prompt.

**Where IQ Engine has theoretical advantage:**
- Source-grounded answers with citations (RAG reduces hallucination)
- IQ layer framing provides structured vocabulary for sales conversations
- Curated content corpus avoids cross-vendor noise
- API-first design enables integration into sales tools, portals, and automation

**Where ChatGPT/Copilot wins today:**
- Speed: GPT-4o responds in 2-3s vs IQ Engine's 10-15s
- Breadth: Can pull from current web, case studies, SEC filings, competitor analysis
- Research: Can actually generate a Duke Energy opportunity brief — IQ Engine 500s
- Formatting: Can produce slides, docs, emails — IQ Engine returns raw JSON
- No setup required: Sales engineers already have it

**The moat IQ Engine needs to build:**
1. Working research/customer brief generation
2. Proprietary content (Azure411 blog, field stories, customer win narratives) that ChatGPT doesn't have
3. Output formats (PPT, Word, email draft) for sales workflow integration
4. Freshness (azure-updates integration) that ChatGPT free tier lacks

---

### 6. Demo Readiness ⭐½ (1.5/5)

**Could you demo this to a customer today?**  
**No. Not without significant risk of embarrassment.**

**What would go wrong in a live demo:**

| Risk | Severity | Likelihood |
|---|---|---|
| `/api/research` returns 500 error | 🔴 Critical | 100% (confirmed) |
| 15-second spinner on live Q&A | 🟠 High | High |
| Customer asks "how is this different from ChatGPT?" | 🟠 High | High |
| Search returns 5 results from same URL | 🟡 Medium | High |
| No output format (everything is raw JSON) | 🟠 High | Certain |
| Customer asks about their specific industry | 🟠 High | High (research is broken) |
| Confidence is always 0.95 | 🟡 Medium | Certain |

**What would impress in a demo:**
- ✅ Health endpoint responds instantly — stable infrastructure
- ✅ Answer structure is readable and well-formatted (when rendered from JSON)
- ✅ IQ layer taxonomy is coherent and differentiating as a concept
- ✅ Azure Firewall/Sentinel/DDoS answer is accurate and well-organized
- ✅ Container Apps vs AKS answer correctly captures the tradeoff

**Minimum viable demo bar:** Fix `/api/research`, add a simple web UI (even a Streamlit prototype), reduce latency to <5s, and fill at least 20 high-quality blog posts in the azure411-blog source.

---

## Prioritized Recommendations

### 🔴 P0 — Ship Blockers (Fix Before Any Customer Exposure)

1. **Fix `/api/research` 500 errors.** This is the entire product value prop. Debug the prompt chain, company context lookup, or route handler. Add proper error bodies (not just "Internal Server Error") to aid debugging. Target: working for energy and finance verticals minimum.

2. **Reduce query latency to <5 seconds.** 15 seconds is demo-killing. Options: streaming responses, pre-warmed embeddings, async chunk retrieval, or response caching for common questions.

3. **Return structured error bodies.** `Internal Server Error` with no JSON body is unacceptable from an API. Add `{"error": "...", "code": "...", "details": "..."}` with actionable messages.

### 🟠 P1 — Demo Readiness (Before First Customer Demo)

4. **Build a minimal web UI.** A Streamlit or Next.js front-end that renders answers as formatted text (not raw JSON) and shows IQ layer context is the difference between a demo and a developer tool.

5. **Fix IQ layer routing in answers.** Answers should identify *which* IQ layer is most relevant to the question and lead with that. A network security question should mention how Foundry IQ could enable AI-assisted threat detection, not just list static services.

6. **Deduplicate search results.** Five results from the same `source_url` looks broken. Implement parent-document deduplication in the retrieval layer.

7. **Add `last_updated` metadata.** Customers will ask "how current is this?" Currently there's no answer.

### 🟡 P2 — Content Gaps (Before Sales Rollout)

8. **Activate and fill azure-updates, azure411-blog, techcommunity sources.** These are the proprietary/differentiated content layers. ms-learn is table stakes — anyone can search that. Proprietary content is the moat.

9. **Tag Foundry IQ content with `foundry-iq` layer** (not `azure-core`). The taxonomy breaks down without consistent tagging. AI Foundry, Azure OpenAI, Azure AI Studio content should carry `foundry-iq`.

10. **Add video transcript volume.** 5 transcripts is not a content source — it's a placeholder. Target 50+ transcripts from Microsoft Build, Ignite, and IQ-focused sessions.

11. **Add customer proof points and case studies** as a source type. Sales engineers prep for meetings with customer stories, not just product docs.

### 🟢 P3 — Competitive Differentiation (Long Term)

12. **Generate output artifacts (not just JSON).** POST /api/research should return a structured customer brief with executive summary, IQ opportunity map, suggested Azure services, customer outcome statements, and recommended next steps — ideally as downloadable Markdown or docx.

13. **Integrate Azure Updates RSS** for always-fresh content so IQ Engine can answer "what's new in Azure AI this month?" better than ChatGPT.

14. **Consider confidence calibration.** If every answer returns 0.95, the score is meaningless. Calibrate against retrieval quality or expose uncertainty when chunks are thin.

15. **Add industry-specific content packages.** Energy sector content (NERC CIP, SCADA modernization, grid analytics) and finance content (DORA, Basel III, real-time payment rails) would make the research output genuinely differentiated from generic LLM responses.

---

## Summary Scorecard

| Category | Score | Stars |
|---|---|---|
| Value Proposition | 2/5 | ⭐⭐ |
| Answer Quality | 3.5/5 | ⭐⭐⭐½ |
| Research Quality | 1/5 | ⭐ |
| Content Coverage | 3/5 | ⭐⭐⭐ |
| Competitive Position | 2.5/5 | ⭐⭐½ |
| Demo Readiness | 1.5/5 | ⭐½ |
| **Overall** | **2.2/5** | **⭐⭐** |

---

## Bottom Line

The bones are good. The IQ layer framework is a genuinely interesting organizational concept. The search and Q&A infrastructure work. The app is live, stable, and versioned. But it is **not a sales tool yet** — it's a search engine with a broken research feature.

Fix `/api/research`, add a real UI, get latency under 5 seconds, and fill the proprietary content sources. With those four changes, this becomes a legitimate demo-ready asset. Without them, a sales engineer is better served by asking Copilot.

The path from 2.2 to 4.0 stars is clear and achievable. Prioritize ruthlessly.
