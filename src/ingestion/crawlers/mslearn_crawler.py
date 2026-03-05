"""
Microsoft Learn Documentation Crawler (ADR-001 / ingestion layer).

Crawls MS Learn pages for Work IQ, Fabric IQ, and Foundry IQ content.

Features:
  - Async HTTP via httpx with configurable concurrency (default 5)
  - BeautifulSoup4 HTML parsing with markdown-style text extraction
  - IQ layer detection from URL path and page content
  - Azure service name tagging from a curated keyword list
  - SHA256 fingerprinting (URL + content) for deduplication
  - Checkpoint / resume — persists crawl state to JSON between runs
  - Rate limiting: max 5 concurrent requests, 1-second batch delay
  - Outputs dicts matching the AI Search index schema

Usage:
    import asyncio
    from src.ingestion.crawlers import MSLearnCrawler, CrawlerConfig

    config = CrawlerConfig(checkpoint_path="crawl_state.json", max_pages=500)
    crawler = MSLearnCrawler(config)
    documents = asyncio.run(crawler.crawl())
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Seed URLs grouped by IQ layer
SEED_URLS: dict[str, list[str]] = {
    "fabric-iq": [
        "https://learn.microsoft.com/en-us/fabric/iq/overview",
        "https://learn.microsoft.com/en-us/fabric/iq/ontology/overview",
    ],
    "foundry-iq": [
        "https://learn.microsoft.com/en-us/azure/ai-services/",
        "https://learn.microsoft.com/en-us/azure/ai-studio/",
    ],
    "work-iq": [
        "https://learn.microsoft.com/en-us/microsoft-365-copilot/",
    ],
}

# Flat list of all seeds for bootstrapping
ALL_SEEDS: list[str] = [url for urls in SEED_URLS.values() for url in urls]

# URL path prefixes that define the crawl boundary per IQ layer
IQ_LAYER_PREFIXES: dict[str, list[str]] = {
    "fabric-iq": [
        "/en-us/fabric/iq",
        "/en-us/fabric/real-time-intelligence",
        "/en-us/fabric/data-engineering",
        "/en-us/fabric/data-factory",
        "/en-us/fabric/data-warehouse",
        "/en-us/fabric/",
    ],
    "foundry-iq": [
        "/en-us/azure/ai-services",
        "/en-us/azure/ai-studio",
        "/en-us/azure/machine-learning",
        "/en-us/azure/cognitive-services",
        "/en-us/azure/openai",
        "/en-us/azure/bot-service",
    ],
    "work-iq": [
        "/en-us/microsoft-365-copilot",
        "/en-us/copilot/microsoft-365",
        "/en-us/microsoft-365/admin",
    ],
}

# Allowed URL prefixes — pages outside these are skipped
ALLOWED_PREFIXES: list[str] = sorted(
    set(
        prefix
        for prefixes in IQ_LAYER_PREFIXES.values()
        for prefix in prefixes
    )
)

# MS Learn host
MS_LEARN_HOST = "learn.microsoft.com"

# Azure service keyword list for tagging
AZURE_SERVICE_KEYWORDS: list[str] = [
    "Azure OpenAI",
    "Azure AI Services",
    "Azure AI Studio",
    "Azure AI Foundry",
    "Azure Machine Learning",
    "Azure Cognitive Services",
    "Azure Bot Service",
    "Azure Search",
    "Azure AI Search",
    "Azure Data Factory",
    "Azure Databricks",
    "Azure Synapse",
    "Azure Fabric",
    "Microsoft Fabric",
    "Azure Storage",
    "Azure Blob Storage",
    "Azure Data Lake",
    "Azure Cosmos DB",
    "Azure SQL",
    "Azure Functions",
    "Azure Service Bus",
    "Azure Event Hub",
    "Azure Event Grid",
    "Azure Container Apps",
    "Azure Kubernetes Service",
    "Azure API Management",
    "Azure Logic Apps",
    "Azure Key Vault",
    "Azure Monitor",
    "Azure Application Insights",
    "Microsoft Copilot",
    "Microsoft 365 Copilot",
    "Power BI",
    "Real-Time Intelligence",
    "OneLake",
    "Lakehouse",
    "Medallion Architecture",
]

# Build a case-insensitive regex from the keyword list
_SERVICE_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in AZURE_SERVICE_KEYWORDS),
    re.IGNORECASE,
)

# HTML elements that contain navigation / UI noise
_NOISE_TAGS = {
    "nav", "header", "footer", "aside", "script", "style",
    "noscript", "form", "button", "svg", "figure",
}

# HTTP headers that mimic a real browser to avoid 403s on MS Learn
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CrawlerConfig:
    """Runtime configuration for the MS Learn crawler."""

    checkpoint_path: str = "mslearn_crawl_state.json"
    """Path to the JSON checkpoint file for resume support."""

    max_pages: int = 2000
    """Hard cap on pages crawled per run (safety valve)."""

    max_concurrent: int = 5
    """Maximum simultaneous HTTP requests."""

    batch_delay_seconds: float = 1.0
    """Seconds to wait between request batches."""

    request_timeout_seconds: float = 30.0
    """HTTP request timeout."""

    follow_links: bool = True
    """Whether to extract and enqueue links found in crawled pages."""

    seeds: list[str] = field(default_factory=lambda: list(ALL_SEEDS))
    """Seed URLs.  Override to limit scope during development."""

    max_retries: int = 3
    """Number of HTTP retry attempts for transient failures."""

    retry_backoff_base: float = 2.0
    """Exponential backoff base (seconds) between retries."""


@dataclass
class CrawledDocument:
    """
    Normalised representation of a single MS Learn page.

    Field names match the AI Search index schema so documents can be passed
    directly to the indexer without further transformation.
    """

    # --- Identity ---
    doc_id: str
    """SHA256(url + content) — stable deduplication key."""

    source_url: str
    """Canonical URL of the page."""

    source_type: str = "ms-learn"

    # --- Content ---
    title: str = ""
    content: str = ""
    """Markdown-cleaned body text."""

    # --- Metadata ---
    published_date: str | None = None
    """ISO-8601 date string if found in page metadata."""

    breadcrumb_path: list[str] = field(default_factory=list)
    """Ordered list of breadcrumb labels, e.g. ['Azure', 'AI Services', 'Overview']."""

    # --- Tags ---
    iq_layers: list[str] = field(default_factory=list)
    """IQ layer tags: 'work-iq', 'fabric-iq', 'foundry-iq' (can be multiple)."""

    azure_services: list[str] = field(default_factory=list)
    """Azure service names found in the page content."""

    # --- Provenance ---
    crawled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    fingerprint: str = ""
    """SHA256 hex digest for change detection (same as doc_id here)."""

    def to_index_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for upload to Azure AI Search."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


@dataclass
class CrawlCheckpoint:
    """Persistent crawl state for resume support."""

    visited: set[str] = field(default_factory=set)
    """URLs that have been fetched (success or permanent failure)."""

    queue: list[str] = field(default_factory=list)
    """URLs pending fetch."""

    failed: dict[str, str] = field(default_factory=dict)
    """URL → error message for pages that failed after all retries."""

    doc_count: int = 0
    """Number of documents successfully crawled so far."""


def _load_checkpoint(path: str) -> CrawlCheckpoint:
    """Load checkpoint from disk.  Returns empty state if file absent."""
    p = Path(path)
    if not p.exists():
        logger.info("No checkpoint found at %s — starting fresh crawl.", path)
        return CrawlCheckpoint()

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cp = CrawlCheckpoint(
            visited=set(data.get("visited", [])),
            queue=data.get("queue", []),
            failed=data.get("failed", {}),
            doc_count=data.get("doc_count", 0),
        )
        logger.info(
            "Checkpoint loaded: %d visited, %d queued, %d failed.",
            len(cp.visited),
            len(cp.queue),
            len(cp.failed),
        )
        return cp
    except Exception as exc:
        logger.warning("Failed to load checkpoint (%s) — starting fresh.", exc)
        return CrawlCheckpoint()


def _save_checkpoint(cp: CrawlCheckpoint, path: str) -> None:
    """Persist crawl state to disk atomically."""
    p = Path(path)
    tmp = p.with_suffix(".tmp")
    payload = {
        "visited": sorted(cp.visited),
        "queue": cp.queue,
        "failed": cp.failed,
        "doc_count": cp.doc_count,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(p)  # atomic rename
    logger.debug("Checkpoint saved: %d visited, %d queued.", len(cp.visited), len(cp.queue))


# ---------------------------------------------------------------------------
# URL utilities
# ---------------------------------------------------------------------------


def _normalise_url(url: str) -> str:
    """
    Strip fragments, query strings, and trailing slashes from an MS Learn URL.
    Ensures locale prefix is present (adds /en-us/ if missing).
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"

    # Ensure we always have the English locale prefix
    if not path.startswith("/en-us"):
        path = "/en-us" + path

    normalised = urlunparse((
        parsed.scheme or "https",
        parsed.netloc or MS_LEARN_HOST,
        path,
        "",   # no params
        "",   # no query
        "",   # no fragment
    ))
    return normalised


def _is_allowed(url: str) -> bool:
    """Return True if *url* is within the permitted crawl boundary."""
    parsed = urlparse(url)
    if parsed.netloc not in (MS_LEARN_HOST, ""):
        return False

    path = parsed.path
    return any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Extract all internal MS Learn links from a parsed page."""
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href: str = anchor["href"].strip()  # type: ignore[index]

        # Skip anchors, mailto, javascript, and external domains
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue

        # Resolve relative URLs
        absolute = urljoin(base_url, href)

        # Keep only MS Learn documentation links
        parsed = urlparse(absolute)
        if parsed.netloc and parsed.netloc != MS_LEARN_HOST:
            continue

        normalised = _normalise_url(absolute)
        if _is_allowed(normalised):
            links.append(normalised)

    return list(dict.fromkeys(links))  # deduplicate while preserving order


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------


def _remove_noise(soup: BeautifulSoup) -> None:
    """Remove navigation, header/footer, and other UI noise in-place."""
    for tag_name in _NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # MS Learn-specific noise selectors
    noise_ids = {"band-nav", "ms-banner", "uhf-header", "uhf-footer", "locale-selector"}
    noise_classes = {
        "breadcrumb", "feedback-section", "is-hidden-mobile",
        "action-container", "doc-feedback", "contribution",
        "page-action-holder", "learn-header", "learn-footer",
        "toc-toggle",
    }
    for tag in soup.find_all(id=noise_ids):
        tag.decompose()
    for cls in noise_classes:
        for tag in soup.find_all(class_=cls):
            tag.decompose()


def _tag_to_markdown(tag: Tag | NavigableString, depth: int = 0) -> str:
    """
    Recursively convert a BeautifulSoup tag tree to a clean markdown-ish string.

    Handles headings, paragraphs, lists, code blocks, and tables.
    """
    if isinstance(tag, NavigableString):
        return str(tag)

    name = tag.name if tag.name else ""
    children_text = "".join(_tag_to_markdown(c, depth + 1) for c in tag.children)

    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(name[1])
        return f"\n\n{'#' * level} {children_text.strip()}\n\n"

    if name == "p":
        return f"\n\n{children_text.strip()}\n\n"

    if name in ("ul", "ol"):
        return f"\n{children_text}\n"

    if name == "li":
        return f"\n- {children_text.strip()}"

    if name == "code":
        return f"`{children_text}`"

    if name == "pre":
        return f"\n\n```\n{children_text.strip()}\n```\n\n"

    if name in ("strong", "b"):
        return f"**{children_text}**"

    if name in ("em", "i"):
        return f"*{children_text}*"

    if name == "a":
        return children_text  # strip links — keep anchor text only

    if name in ("table",):
        return f"\n\n{children_text}\n\n"

    if name in ("tr",):
        return f"\n| {' | '.join(c.strip() for c in children_text.split('|') if c.strip())} |"

    if name in ("th", "td"):
        return f"{children_text.strip()} |"

    if name in ("br",):
        return "\n"

    if name in ("hr",):
        return "\n---\n"

    if name in ("div", "section", "article", "main", "span"):
        return children_text

    return children_text


def _clean_text(text: str) -> str:
    """Collapse excessive whitespace while preserving paragraph breaks."""
    # Collapse runs of spaces/tabs
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_title(soup: BeautifulSoup) -> str:
    """Extract the page title, preferring the <h1> over <title>."""
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(separator=" ", strip=True)

    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):  # type: ignore[union-attr]
        return str(og_title["content"]).strip()  # type: ignore[index]

    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(strip=True)
        # Strip " | Microsoft Learn" suffix
        return re.sub(r"\s*\|\s*Microsoft\s+Learn\s*$", "", raw)

    return ""


def _extract_published_date(soup: BeautifulSoup) -> str | None:
    """
    Extract published / last-updated date from MS Learn page metadata.

    MS Learn embeds a `<time>` element or a meta tag with the article date.
    """
    # <time datetime="..."> element
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):  # type: ignore[union-attr]
        return str(time_tag["datetime"])  # type: ignore[index]

    # <meta name="ms.date" content="..."> or <meta name="date" content="...">
    for meta_name in ("ms.date", "date", "article:published_time"):
        meta = soup.find("meta", attrs={"name": meta_name}) or soup.find(
            "meta", attrs={"property": meta_name}
        )
        if meta and meta.get("content"):  # type: ignore[union-attr]
            return str(meta["content"])  # type: ignore[index]

    return None


def _extract_breadcrumb(soup: BeautifulSoup) -> list[str]:
    """
    Extract breadcrumb navigation labels.

    MS Learn renders breadcrumbs as <nav aria-label="breadcrumb"> or
    as a JSON-LD BreadcrumbList structured data block.
    """
    # Try JSON-LD structured data first (most reliable)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = next(
                    (d for d in data if d.get("@type") == "BreadcrumbList"),
                    None,
                )
            if isinstance(data, dict) and data.get("@type") == "BreadcrumbList":
                items = data.get("itemListElement", [])
                return [item.get("name", "").strip() for item in items if item.get("name")]
        except (json.JSONDecodeError, AttributeError):
            continue

    # Fallback: look for a <nav> with role/aria breadcrumb markers
    nav = soup.find("nav", attrs={"aria-label": re.compile(r"breadcrumb", re.I)})
    if nav:
        return [
            a.get_text(strip=True)
            for a in nav.find_all("a")
            if a.get_text(strip=True)
        ]

    # Fallback: ol.breadcrumb pattern
    bc_ol = soup.find("ol", class_=re.compile(r"breadcrumb", re.I))
    if bc_ol:
        return [li.get_text(strip=True) for li in bc_ol.find_all("li")]

    return []


def _extract_body_text(soup: BeautifulSoup) -> str:
    """
    Extract the main article body from an MS Learn page.

    Tries the <main> / article / #main-content container first, then falls
    back to the full document.
    """
    # MS Learn wraps content in <main> or a div with id="main-content"
    main_content = (
        soup.find("main")
        or soup.find("div", id="main-content")
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"content|article|doc", re.I))
    )

    if not main_content:
        main_content = soup.body or soup

    # Remove the h1 (already captured as title) to avoid duplication
    h1 = main_content.find("h1")  # type: ignore[union-attr]
    if h1:
        h1.decompose()

    raw_md = _tag_to_markdown(main_content)  # type: ignore[arg-type]
    return _clean_text(raw_md)


# ---------------------------------------------------------------------------
# Tagging helpers
# ---------------------------------------------------------------------------


def _detect_iq_layers(url: str, content: str) -> list[str]:
    """
    Determine which IQ layers this page belongs to.

    Priority: URL path match (deterministic) → content keyword fallback.
    A page can belong to multiple layers.
    """
    parsed_path = urlparse(url).path
    layers: set[str] = set()

    for layer, prefixes in IQ_LAYER_PREFIXES.items():
        if any(parsed_path.startswith(pfx) for pfx in prefixes):
            layers.add(layer)

    # Content-level fallback: look for layer mentions in the body
    if not layers:
        lower = content.lower()
        if any(kw in lower for kw in ("fabric iq", "microsoft fabric", "real-time intelligence", "onelake")):
            layers.add("fabric-iq")
        if any(kw in lower for kw in ("ai foundry", "azure openai", "ai studio", "cognitive services")):
            layers.add("foundry-iq")
        if any(kw in lower for kw in ("microsoft 365 copilot", "work iq", "m365 copilot")):
            layers.add("work-iq")

    return sorted(layers)


def _detect_azure_services(content: str) -> list[str]:
    """Return deduplicated list of Azure service names found in *content*."""
    found = _SERVICE_PATTERN.findall(content)
    # Normalise casing by mapping back to the canonical keyword
    canonical: dict[str, str] = {kw.lower(): kw for kw in AZURE_SERVICE_KEYWORDS}
    unique = list(dict.fromkeys(canonical.get(match.lower(), match) for match in found))
    return unique


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def _compute_fingerprint(url: str, content: str) -> str:
    """SHA256(url + content) — consistent with fingerprint.py convention."""
    payload = f"{url}:{content}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Page parser (synchronous — called from async context via threadpool)
# ---------------------------------------------------------------------------


def _parse_page(url: str, html: str) -> CrawledDocument | None:
    """
    Parse a raw HTML response into a CrawledDocument.

    Returns None if the page does not contain meaningful content
    (e.g., redirect pages, empty docs, 404 soft pages).

    Extraction order matters:
      1. Extract metadata that depends on elements removed by _remove_noise
         (breadcrumb JSON-LD lives in <script> tags; published date in <meta>).
      2. Remove noise.
      3. Extract body text from the cleaned DOM.
    """
    soup = BeautifulSoup(html, "html.parser")

    # --- Phase 1: extract metadata BEFORE noise removal ---
    # _remove_noise strips <script> tags (kills JSON-LD) and .breadcrumb classes
    title = _extract_title(soup)
    published_date = _extract_published_date(soup)
    breadcrumb = _extract_breadcrumb(soup)

    # --- Phase 2: clean the DOM ---
    _remove_noise(soup)

    # --- Phase 3: extract body text from cleaned DOM ---
    body_text = _extract_body_text(soup)

    if not body_text or len(body_text) < 50:
        logger.debug("Skipping thin page: %s (content length %d)", url, len(body_text))
        return None

    iq_layers = _detect_iq_layers(url, body_text)
    azure_services = _detect_azure_services(body_text)
    fingerprint = _compute_fingerprint(url, body_text)

    return CrawledDocument(
        doc_id=fingerprint,
        source_url=url,
        source_type="ms-learn",
        title=title,
        content=body_text,
        published_date=published_date,
        breadcrumb_path=breadcrumb,
        iq_layers=iq_layers,
        azure_services=azure_services,
        crawled_at=datetime.now(timezone.utc).isoformat(),
        fingerprint=fingerprint,
    )


def _extract_new_links(url: str, html: str) -> list[str]:
    """Extract valid, allowed outbound links from a page."""
    soup = BeautifulSoup(html, "html.parser")
    return _extract_links(soup, url)


# ---------------------------------------------------------------------------
# Async HTTP fetch with retry
# ---------------------------------------------------------------------------


async def _fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int,
    backoff_base: float,
) -> str | None:
    """
    Fetch *url* with exponential backoff retries.

    Returns the response text on success, or None after exhausting retries.
    """
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url, follow_redirects=True)

            if response.status_code == 200:
                return response.text

            if response.status_code in (301, 302, 307, 308):
                # httpx follows redirects automatically; reaching here means a loop
                logger.warning("Redirect loop detected for %s — skipping.", url)
                return None

            if response.status_code == 404:
                logger.debug("404 for %s — skipping.", url)
                return None

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", backoff_base ** (attempt + 1)))
                logger.warning("Rate limited on %s — waiting %ds.", url, retry_after)
                await asyncio.sleep(retry_after)
                continue

            if response.status_code >= 500:
                wait = backoff_base ** attempt
                logger.warning(
                    "Server error %d for %s (attempt %d/%d) — retrying in %.1fs.",
                    response.status_code, url, attempt + 1, max_retries + 1, wait,
                )
                await asyncio.sleep(wait)
                continue

            logger.debug("Unexpected status %d for %s.", response.status_code, url)
            return None

        except httpx.TimeoutException:
            wait = backoff_base ** attempt
            logger.warning("Timeout fetching %s (attempt %d/%d) — retrying in %.1fs.",
                           url, attempt + 1, max_retries + 1, wait)
            await asyncio.sleep(wait)

        except httpx.RequestError as exc:
            wait = backoff_base ** attempt
            logger.warning("Request error fetching %s: %s (attempt %d/%d) — retrying in %.1fs.",
                           url, exc, attempt + 1, max_retries + 1, wait)
            await asyncio.sleep(wait)

    logger.error("Giving up on %s after %d attempts.", url, max_retries + 1)
    return None


# ---------------------------------------------------------------------------
# Main crawler class
# ---------------------------------------------------------------------------


class MSLearnCrawler:
    """
    Async crawler for Microsoft Learn documentation.

    Designed to be instantiated once per run.  Call ``crawl()`` to produce
    a list of ``CrawledDocument`` instances ready for chunking and indexing.

    Example::

        config = CrawlerConfig(checkpoint_path="state.json", max_pages=200)
        crawler = MSLearnCrawler(config)
        docs = await crawler.crawl()
        index_records = [doc.to_index_dict() for doc in docs]
    """

    def __init__(self, config: CrawlerConfig | None = None) -> None:
        self.config = config or CrawlerConfig()
        self._checkpoint: CrawlCheckpoint | None = None
        self._documents: list[CrawledDocument] = []
        self._semaphore: asyncio.Semaphore | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def crawl(self) -> list[CrawledDocument]:
        """
        Execute the full crawl.

        Seeds the queue from the checkpoint (or seed URLs on first run),
        processes pages in batches, and returns all crawled documents.

        Thread-safe for a single crawler instance per event loop.
        """
        self._checkpoint = _load_checkpoint(self.config.checkpoint_path)
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._documents = []

        cp = self._checkpoint

        # Seed the queue on first run (checkpoint queue is empty)
        if not cp.queue and not cp.visited:
            logger.info("Seeding crawl queue with %d URLs.", len(self.config.seeds))
            cp.queue = list(dict.fromkeys(_normalise_url(u) for u in self.config.seeds))

        logger.info(
            "Starting crawl: %d pages in queue, %d already visited, limit %d.",
            len(cp.queue), len(cp.visited), self.config.max_pages,
        )

        async with httpx.AsyncClient(
            headers=_DEFAULT_HEADERS,
            timeout=self.config.request_timeout_seconds,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=self.config.max_concurrent + 2,
                max_keepalive_connections=self.config.max_concurrent,
            ),
        ) as client:
            await self._process_queue(client, cp)

        _save_checkpoint(cp, self.config.checkpoint_path)

        logger.info(
            "Crawl complete: %d documents, %d visited, %d failed.",
            len(self._documents),
            len(cp.visited),
            len(cp.failed),
        )
        return self._documents

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    async def _process_queue(
        self, client: httpx.AsyncClient, cp: CrawlCheckpoint
    ) -> None:
        """
        Drain the crawl queue in batches respecting concurrency and rate limits.

        Saves checkpoint after every batch so progress survives interruption.
        """
        config = self.config
        batch_size = config.max_concurrent

        while cp.queue:
            if len(cp.visited) >= config.max_pages:
                logger.info(
                    "Reached page limit (%d) — stopping crawl.", config.max_pages
                )
                break

            # Pull next batch from the front of the queue
            batch = []
            while cp.queue and len(batch) < batch_size:
                url = cp.queue.pop(0)
                if url not in cp.visited:
                    batch.append(url)

            if not batch:
                continue

            logger.info(
                "Fetching batch of %d URLs (visited=%d, queued=%d).",
                len(batch), len(cp.visited), len(cp.queue),
            )

            # Fire batch concurrently
            tasks = [
                self._process_one(client, url, cp)
                for url in batch
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Checkpoint after each batch
            _save_checkpoint(cp, config.checkpoint_path)

            # Rate limit delay between batches
            if cp.queue:
                await asyncio.sleep(config.batch_delay_seconds)

    async def _process_one(
        self,
        client: httpx.AsyncClient,
        url: str,
        cp: CrawlCheckpoint,
    ) -> None:
        """
        Fetch, parse, and enqueue links for a single URL.

        Guards with the semaphore to respect max_concurrent.
        """
        assert self._semaphore is not None

        async with self._semaphore:
            # Double-check under semaphore in case of race in gather
            if url in cp.visited:
                return

            cp.visited.add(url)

            html = await _fetch_with_retry(
                client, url,
                self.config.max_retries,
                self.config.retry_backoff_base,
            )

            if html is None:
                cp.failed[url] = "fetch_failed"
                logger.debug("Failed to fetch %s.", url)
                return

            # Parse in a thread so we don't block the event loop on CPU work
            loop = asyncio.get_event_loop()
            doc = await loop.run_in_executor(None, _parse_page, url, html)

            if doc is not None:
                self._documents.append(doc)
                cp.doc_count += 1
                logger.debug(
                    "Crawled [%d] %s — layers=%s services=%d",
                    cp.doc_count, url, doc.iq_layers, len(doc.azure_services),
                )

            # Discover and enqueue new links
            if self.config.follow_links:
                new_links = await loop.run_in_executor(
                    None, _extract_new_links, url, html
                )
                enqueued = 0
                for link in new_links:
                    if link not in cp.visited and link not in cp.queue:
                        cp.queue.append(link)
                        enqueued += 1
                if enqueued:
                    logger.debug("Enqueued %d new links from %s.", enqueued, url)


# ---------------------------------------------------------------------------
# CLI entry point for ad-hoc testing
# ---------------------------------------------------------------------------


async def _cli_main() -> None:
    """
    Quick smoke-test:  crawl a handful of pages and print a summary.

    Run with: python -m src.ingestion.crawlers.mslearn_crawler
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    config = CrawlerConfig(
        checkpoint_path="/tmp/mslearn_crawl_test.json",
        max_pages=20,        # Tiny limit for smoke-test
        follow_links=True,
        seeds=ALL_SEEDS,
    )

    crawler = MSLearnCrawler(config)
    docs = await crawler.crawl()

    print(f"\n{'='*60}")
    print(f"Crawled {len(docs)} documents")
    print(f"{'='*60}")
    for doc in docs[:5]:
        print(f"\nTitle   : {doc.title}")
        print(f"URL     : {doc.source_url}")
        print(f"Layers  : {doc.iq_layers}")
        print(f"Services: {doc.azure_services[:3]}...")
        print(f"Breadcrumb: {' > '.join(doc.breadcrumb_path)}")
        print(f"Date    : {doc.published_date}")
        print(f"Chars   : {len(doc.content)}")
        print(f"Fingerprint: {doc.fingerprint[:16]}...")


if __name__ == "__main__":
    asyncio.run(_cli_main())
