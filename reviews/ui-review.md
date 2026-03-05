# Azure IQ Engine — UI/UX Review
**App URL:** https://ca-iq-engine-01.icygrass-2e1bb7f3.centralus.azurecontainerapps.io  
**Version Tested:** v0.3.8 → v0.3.9 (version bumped during testing — live deployment)  
**Review Date:** 2026-03-05  
**Reviewer:** Astra (subagent review)  
**Scope:** All 4 tabs (Ask, Research, Explore, Quiz), visual design, interactions, responsiveness, accessibility, content quality, edge cases

---

## Executive Summary

Azure IQ Engine is a well-structured, visually clean knowledge app with strong content quality in the Ask and Research tabs. The dark/light theme, quick-action shortcuts, and responsive design are solid foundations. However, the **Quiz tab is completely broken** (HTTP 500), there are **source contamination and deduplication problems** across tabs, and **accessibility implementation is incomplete**, particularly around ARIA tab state management and button semantics.

---

## Issue Registry

| ID | Severity | Area | Title |
|----|----------|------|-------|
| IQ-01 | 🔴 Critical | Quiz | HTTP 500 on every quiz generation attempt |
| IQ-02 | 🟠 High | Ask | Source contamination — Cosmos DB cited for Key Vault query |
| IQ-03 | 🟠 High | Ask/Explore | Duplicate sources not deduplicated |
| IQ-04 | 🟠 High | Explore | Duplicate document chunks in search results |
| IQ-05 | 🟡 Medium | All Tabs | `aria-selected` not updated on tab navigation |
| IQ-06 | 🟡 Medium | All Tabs | All buttons default to `type="submit"` |
| IQ-07 | 🟡 Medium | Ask | Inline citation refs [1][2][3] not hyperlinked |
| IQ-08 | 🟡 Medium | Ask | Knowledge gap for Key Vault provisioning — no redirect to official docs |
| IQ-09 | 🟡 Medium | Ask | All source relevance scores display as 100% |
| IQ-10 | 🟢 Low | Ask | Export Markdown button has no visual feedback |
| IQ-11 | 🟢 Low | Research | Result area scroll not obvious — content appears cut off |
| IQ-12 | 🟢 Low | Mobile | Header subtitle wraps 3 lines at 375px |
| IQ-13 | 🟢 Low | All Tabs | Icon-only header buttons rely on `title` instead of `aria-label` |
| IQ-14 | 🟢 Low | Research | First submission sometimes silently fails (race condition) |
| IQ-15 | 🟢 Low | Ask | Version badge duplicated in input bar |

---

## Detailed Findings

---

### IQ-01 — 🔴 CRITICAL | Quiz Tab: HTTP 500 on Every Generation Attempt

**Description:**  
The Quiz tab generates an HTTP 500 Internal Server Error on every attempt. Two errors were observed across three tries:
- First attempt: `"⚠️ Could not parse quiz. Try again."`
- Second and third attempts: `"⚠️ Quiz generation failed: HTTP 500"`

All topic/difficulty combinations tested:
- All topics + Intermediate → HTTP 500
- Foundry IQ + Beginner → HTTP 500

**Screenshot Description:**  
The Generate Quiz button shows "Generating..." (loading state works), but the quiz area shows a red/pink error banner with the warning icon and error message. The rest of the page is completely empty below.

**Impact:**  
The entire Quiz tab feature is non-functional. No quiz can be generated under any configuration.

**Fix Recommendation:**  
1. Check the `/api/quiz` (or equivalent) backend endpoint for unhandled exceptions
2. Validate JSON structure returned by the LLM — the parse error on the first attempt suggests the LLM response isn't consistently structured as valid JSON
3. Add a retry with exponential backoff for transient failures
4. Add a fallback message: "Quiz generation is temporarily unavailable. Try the Ask tab instead."
5. Log the full stack trace on the server and set up an Application Insights alert for 5xx on this endpoint

---

### IQ-02 — 🟠 HIGH | Ask Tab: Source Contamination

**Description:**  
When asking "How do I set up Azure Key Vault?", the sources panel lists:
- **Azure Cosmos DB documentation** (100%) — appears **twice**
- Azure Key Vault (100%) — appears 3 times

"Azure Cosmos DB documentation" is completely unrelated to Azure Key Vault setup. This misleads users into thinking the answer was grounded in Cosmos DB content.

**Screenshot Description:**  
Sources panel expanded shows 5 sources listed. The first two are identically labeled "Azure Cosmos DB documentation" linking to `https://learn.microsoft.com/en-us/azure/cosmos-db`, scored 100%.

**Impact:**  
Erodes trust in the grounding/citation quality. Users may question the accuracy of all responses if unrelated sources appear.

**Fix Recommendation:**  
1. Review the chunking strategy — it's likely that some Key Vault documentation chunks were co-indexed with Cosmos DB content in the same document boundary
2. Implement source-level deduplication before rendering (group by URL and show highest-scored chunk only)
3. Filter out sources with semantic similarity below a meaningful threshold (e.g., < 70%) from the display
4. Add a "Why this source?" tooltip to help users understand relevance

---

### IQ-03 — 🟠 HIGH | Duplicate Sources Displayed

**Description:**  
In the Ask tab sources panel, identical source URLs appear multiple times:
- "Azure Cosmos DB documentation" appears twice, same URL
- "Azure Key Vault" appears three times, same URL

All duplicates show 100% relevance. This likely reflects that multiple document *chunks* from the same document were retrieved.

**Fix Recommendation:**  
Deduplicate the source list by URL before rendering. Keep the chunk with the highest relevance score. Show a count if multiple chunks were retrieved: "Azure Key Vault (3 chunks)".

---

### IQ-04 — 🟠 HIGH | Explore Tab: Duplicate Document Chunks in Search Results

**Description:**  
When searching "container apps" filtered to Blog Post, 10 results are returned from 56 blog posts, but with significant duplication:
- "Application Gateway for Containers" appears **twice** (different excerpts, same URL)
- "Migrate First, Modernize Later" appears **twice** (different excerpts, same URL)
- "Azure AD B2C: A Modern and Secure Identity Solution" appears **four times** (different excerpts, same URL — and this article isn't closely related to "container apps")

The result count says "10 results" but there are effectively only ~5 unique documents.

**Screenshot Description:**  
Results list shows 10 cards in a grid layout. Several cards have identical titles with different excerpt text and slightly different relevance scores. Tag chips below each card show `blog-post`, `foundry_iq`, etc.

**Impact:**  
High visual noise and apparent signal-to-noise quality issue. Users see the same blog post 4 times for a single search.

**Fix Recommendation:**  
1. Deduplicate by source URL, keeping the highest-scored chunk per document
2. Show result count *after* deduplication: "5 unique documents (from 10 chunks)"
3. Consider grouping multiple chunks from the same article into a single expandable card

---

### IQ-05 — 🟡 MEDIUM | `aria-selected` Not Updated on Tab Navigation

**Description:**  
The tab bar has `role="tab"` on each tab element. However, `aria-selected` is **only set on the Ask tab** (hardcoded `aria-selected="true"`) and is **null on Research, Explore, and Quiz tabs**. When the user navigates to Research, the Research tab gets the CSS class `active` and `tab active` but the DOM attribute `aria-selected` is never updated.

```
Ask tab:      role=tab, aria-selected=true   ← only one with value
Research tab: role=tab, aria-selected=null   ← not updated after click
Explore tab:  role=tab, aria-selected=null
Quiz tab:     role=tab, aria-selected=null
```

**Impact:**  
Screen readers (NVDA, VoiceOver, JAWS) will not announce which tab is currently active when navigating between tabs. Users relying on assistive technology will hear no state change.

**Fix Recommendation:**  
In the tab switch handler, update `aria-selected` dynamically:
```javascript
tabs.forEach(tab => tab.setAttribute('aria-selected', 'false'));
activeTab.setAttribute('aria-selected', 'true');
```
Also ensure the tab panel has `role="tabpanel"` with `aria-labelledby` pointing to the active tab ID.

---

### IQ-06 — 🟡 MEDIUM | All Buttons Default to `type="submit"`

**Description:**  
Every `<button>` element in the app lacks an explicit `type` attribute. In HTML, the default button type inside a `<form>` element is `type="submit"`. All 14 buttons in the DOM report `type="submit"`:

```
🗑️ Clear chat history: type=submit
📥 Export as Markdown: type=submit
🌑 Theme toggle: type=submit
⚡ What's new?: type=submit
⚖️ Compare vs competitors: type=submit
... (all others same)
```

**Impact:**  
If any button is placed inside or near a form element, pressing Enter on an input could accidentally trigger the wrong submit. Also semantically incorrect — non-submit actions should use `type="button"`.

**Fix Recommendation:**  
Add `type="button"` to all non-submit buttons:
```html
<button type="button" id="clear-btn" title="Clear chat history">🗑️</button>
<button type="button" id="export-md-btn" title="Export as Markdown">📥</button>
```
Only the actual form submit buttons (Send, Generate Quiz, Generate IQ Assessment, Search) should have `type="submit"`.

---

### IQ-07 — 🟡 MEDIUM | Inline Citation Refs Not Hyperlinked

**Description:**  
Ask tab responses include inline citations like `[3][5]` and `[4][5]` within the response text:
- "Set and retrieve keys using the Azure portal [3][5]"
- "Authentication overview and basic concepts [4]"

These citation numbers are rendered as plain text — they are **not interactive links**. Users cannot click [3] to jump to source #3 in the sources panel.

**Fix Recommendation:**  
Convert inline citation markers to anchor links that scroll to or highlight the corresponding source:
```html
<sup><a href="#source-3" class="cite-ref">[3]</a></sup>
```
Or implement a hover tooltip showing the source title/URL when hovering over a citation number.

---

### IQ-08 — 🟡 MEDIUM | Knowledge Gap for Key Vault Provisioning

**Description:**  
The Ask response for "How do I set up Azure Key Vault?" correctly states:
> "The provided context does **not** contain specific procedural steps for initially setting up or provisioning an Azure Key Vault instance."

However, it does not provide a direct link to the official Microsoft documentation where the user *can* find this. It only says "you would need to consult the official Azure Key Vault documentation directly" with no URL.

**Impact:**  
Users are told where they *can't* find info but not directed to where they *can*. The response should proactively bridge the gap.

**Fix Recommendation:**  
When the agent detects a knowledge gap, add a fallback suggestion:
> "For complete provisioning steps, see: [Quickstart: Create a key vault using the Azure portal](https://learn.microsoft.com/en-us/azure/key-vault/general/quick-create-portal)"

Consider adding an "official docs search" fallback action that searches Azure documentation directly when the indexed corpus is insufficient.

---

### IQ-09 — 🟡 MEDIUM | All Source Relevance Scores Display as 100%

**Description:**  
Every source in the Ask tab sources panel shows "100%" regardless of actual semantic relevance. This is inconsistent — if all retrieved sources were truly 100% relevant, the "Azure Cosmos DB documentation" would not appear for a Key Vault query.

**Screenshot Description:**  
5-source panel shows all five entries at "100%" — two Cosmos DB and three Key Vault entries.

**Impact:**  
The relevance percentage provides false confidence. It either reflects the maximum possible score being displayed incorrectly, or it's a display normalization issue that rounds to 100.

**Fix Recommendation:**  
1. Show actual normalized relevance scores (e.g., 0.0–1.0 as percentage)
2. Apply a color gradient: green (90%+), yellow (70–89%), orange (<70%)
3. Consider hiding sources below a threshold (e.g., <60%) unless user expands an "additional sources" section

---

### IQ-10 — 🟢 LOW | Export Markdown: No Visual Feedback

**Description:**  
Clicking the 📥 "Export as Markdown" button produces no visible UI response — no toast notification, no loading indicator, no confirmation that a file was downloaded or copied.

**Fix Recommendation:**  
Add a brief toast/snackbar: "Chat exported to iq-session-{date}.md" or "Copied to clipboard" depending on the export method.

---

### IQ-11 — 🟢 LOW | Research Tab Result Area Scroll Not Intuitive

**Description:**  
The Research tab displays results in a scrollable `<div>` (class `research-result`) with a fixed height inside the page. At normal zoom, the "Recommended Approach" section is cut off at the bottom of the viewport. The user must scroll *within the result container* — but there's no visible scrollbar, scroll indicator, or "more content below" hint.

**Fix Recommendation:**  
1. Add a subtle scroll shadow or fade at the bottom of the result container when content overflows
2. Show a "▼ Scroll for more" hint when content is clipped
3. Or allow the result container to grow to full height and let the page scroll naturally

---

### IQ-12 — 🟢 LOW | Header Subtitle Wraps 3 Lines on Mobile (375px)

**Description:**  
At 375px viewport width (iPhone-sized), the subtitle "Unified Knowledge for Work IQ · Fabric IQ · Foundry IQ" wraps to 3 lines, making the header very tall and reducing visible content area.

**Screenshot Description:**  
Mobile view shows the header taking up about 1/4 of the screen height before even reaching the tab bar.

**Fix Recommendation:**  
- Shorten the subtitle on mobile: "Work IQ · Fabric IQ · Foundry IQ" (drop "Unified Knowledge for")
- Or use a CSS breakpoint to hide the subtitle entirely on viewports < 400px, since the branding is visible via the H1 title

---

### IQ-13 — 🟢 LOW | Icon-Only Buttons Rely on `title` Instead of `aria-label`

**Description:**  
Two header buttons use only `title` for accessible naming:
- 🗑️ button: `title="Clear chat history"` (no `aria-label`)
- 📥 button: `title="Export as Markdown"` (no `aria-label`)

The theme toggle is correct: it has `aria-label="Toggle dark/light theme"`.

Additionally, there is a minor inconsistency: the `title` says "Toggle light/dark theme" while `aria-label` says "Toggle dark/light theme."

**Fix Recommendation:**  
Add explicit `aria-label` to all icon-only buttons. `title` alone is not reliably announced by all screen readers in all modes:
```html
<button type="button" aria-label="Clear chat history" title="Clear chat history">🗑️</button>
<button type="button" aria-label="Export conversation as Markdown" title="Export as Markdown">📥</button>
```
Also normalize the wording between `title` and `aria-label` on the theme toggle.

---

### IQ-14 — 🟢 LOW | Research Tab: First Submission Sometimes Silently Fails

**Description:**  
During testing, the first "Generate IQ Assessment" submission for Duke Energy appeared to complete (button returned to "Generate IQ Assessment" from "Researching...") but produced no results — the `research-result` div was empty. Only the second attempt produced output.

This may be a cold-start latency issue on the backend, a race condition in state management, or a silent timeout.

**Fix Recommendation:**  
1. Add a timeout handler: if no result after N seconds, show "Generation timed out. Please try again."
2. Implement retry logic with a user-visible "Retrying..." state
3. Log the first-attempt failure in App Insights to understand frequency

---

### IQ-15 — 🟢 LOW | Version Badge Duplicated in Input Bar

**Description:**  
The version number "v0.3.8/v0.3.9" appears in two places:
1. Header right-side: `v0.3.8` (correct, primary location)
2. Inside the input bar area, after the agent selector dropdown: `• 0.3.9` (secondary, redundant)

**Screenshot Description:**  
The bottom input bar shows: `[🤖 Auto-route ▼] [• 0.3.9] [Ask about... textarea] [Send]`

**Fix Recommendation:**  
Remove the version indicator from the input bar. The header badge is sufficient. If version is needed for support context, expose it only in a "About" modal or in the footer.

---

## Positive Findings

These aspects are working well and should be preserved:

| Feature | Assessment |
|---------|------------|
| **Dark/Light theme toggle** | Works instantly, consistent across all tabs, smooth transition |
| **Quick action buttons** | Pre-fill query text and navigate to correct tab. "Research a company" shortcut is especially useful |
| **Ask response quality** | Well-structured, uses bold headers and bullets, performance metadata (⏱ 14.2s, 🔢 1710 tokens, 📊 95%) is excellent |
| **Source links** | All source citations in panels are real, clickable links that open in new tabs |
| **Research content quality** | Duke Energy assessment was detailed, industry-specific, with phased implementation plan |
| **Explore source filtering** | Dropdown filter by Ms Learn / Blog Post / Video Transcript works correctly |
| **XSS protection** | Script injection via input is safely escaped — `<script>alert('xss')</script>` rendered as plain text |
| **Empty query handling** | Empty send clicks are silently ignored — no crash or API call |
| **Long query handling** | Textarea auto-expands for multi-paragraph queries |
| **Tablet layout (768px)** | Clean and functional, minor button wrap on second row |
| **Mobile layout (375px)** | Functional, tabs fit in single row, input bar remains usable |
| **Footer corpus stats** | "2,394 chunks indexed — 2333 from Ms Learn, 56 from Blog Post, 5 from Video Transcript" provides useful transparency |
| **AI agent selector** | 6 specialized agents (Auto-route, IQ Architect, Azure Navigator, Story Weaver, Latest Updates, Competitive Context) |
| **Heading hierarchy** | H1 → H2 → H3 → H4 is semantically valid |

---

## Responsiveness Summary

| Viewport | Observations |
|----------|-------------|
| **Desktop (1200px)** | Excellent. All elements fit cleanly. Quick action buttons in one row. |
| **Tablet (768px)** | Good. Tabs + quick actions mostly fit. "Research a company" wraps to row 2. |
| **Mobile (375px)** | Functional. Header subtitle wraps 3 lines. Quick action buttons wrap to 3 rows. Input bar remains accessible. |

---

## Accessibility Summary

| Check | Status |
|-------|--------|
| Heading structure (H1 → H2 → H3 → H4) | ✅ Pass |
| Tabs have `role="tab"` | ✅ Pass |
| Active tab `aria-selected` updates on click | ❌ Fail — only Ask tab has hardcoded `aria-selected="true"` |
| Form inputs have accessible labels | ⚠️ Partial — some use `aria-label`, others have no label |
| Buttons have accessible names | ⚠️ Partial — icon buttons rely on `title` only, not `aria-label` |
| Button type attributes | ❌ Fail — all default to `type="submit"` |
| Color contrast (light mode) | ✅ Good — dark text on light backgrounds |
| Color contrast (dark mode) | ✅ Good — light text on dark backgrounds |
| Focus indicators | ⚠️ Not fully tested — default browser focus ring only |
| Keyboard-only navigation | ⚠️ Partially functional — tab order follows DOM flow but quick action shortcuts are keyboard-reachable |

---

## Prioritized Fix Roadmap

### Sprint 1 — Critical + High (Fix Now)
1. **IQ-01**: Fix Quiz HTTP 500 — investigate and fix backend `/api/quiz` endpoint
2. **IQ-02**: Fix source contamination — review chunk indexing and source attribution
3. **IQ-03 + IQ-04**: Implement source deduplication by URL (both Ask sources panel and Explore results)

### Sprint 2 — Medium (Next Sprint)
4. **IQ-05**: Fix `aria-selected` tab state update on navigation
5. **IQ-06**: Add `type="button"` to all non-submit buttons
6. **IQ-07**: Make inline citation refs clickable anchors to source panel entries
7. **IQ-08**: Add official docs fallback link when knowledge gap is detected
8. **IQ-09**: Fix relevance score display — show actual scores, add color coding

### Sprint 3 — Low (Polish)
9. **IQ-10**: Add export feedback toast
10. **IQ-11**: Add scroll shadow/fade for Research result container overflow
11. **IQ-12**: Responsive mobile header subtitle truncation
12. **IQ-13**: Add explicit `aria-label` to icon-only buttons
13. **IQ-14**: Add timeout/error handling to Research first-submit
14. **IQ-15**: Remove version badge from input bar

---

*Review conducted via automated browser testing with visual inspection, ARIA snapshot analysis, and DOM evaluation. Screenshots captured at desktop (1200px), tablet (768px), and mobile (375px) viewports.*
