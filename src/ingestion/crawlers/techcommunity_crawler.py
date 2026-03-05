"""
Microsoft Tech Community Crawler.

Crawls blog posts from three Tech Community sections:

    • Azure Dev Community Blog  — /blog/azuredevcommunityblog
    • Azure AI Blog             — /blog/azure-ai
    • FastAbord (Fabric) Blog   — /blog/fastabordblog

Uses httpx + BeautifulSoup4 for HTML parsing.  Max 3 concurrent requests
with a 2-second inter-request delay to be a polite crawler.

Checkpoint/resume: persists the set of crawled URLs and the newest published
date per blog section.  SHA-256 fingerprint = hash(url + title + body[:2048]).

Dependencies:
    pip install httpx beautifulsoup4
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://techcommunity.microsoft.com"

BLOG_ENTRY_POINTS: list[dict[str, str]] = [
    {
        "url": "https://techcommunity.microsoft.com/blog/azuredevcommunityblog",
        "label": "azure-dev-community",
    },
    {
        "url": "https://techcommunity.microsoft.com/blog/azure-ai",
        "label": "azure-ai",
    },
    {
        "url": "https://techcommunity.microsoft.com/blog/fastabordblog",
        "label": "fabric",
    },
]

DEFAULT_CHECKPOINT_PATH = Path("checkpoints/techcommunity_checkpoint.json")
REQUEST_DELAY_SECONDS = 2.0
MAX_CONCURRENT = 3
MAX_PAGES_PER_BLOG = 20       # Safety limit — each page ≈ 10-20 posts
REQUEST_TIMEOUT = 30.0
USER_AGENT = "AzureIQEngine-Crawler/1.0 (+https://github.com/azure-iq-engine)"

# IQ layer signals
IQ_LAYER_SIGNALS: dict[str, list[str]] = {
    "work_iq": [
        "copilot", "m365", "microsoft 365", "teams", "viva", "sharepoint",
        "power platform", "power automate", "power apps", "power bi",
        "productivity", "workplace",
    ],
    "fabric_iq": [
        "fabric", "onelake", "lakehouse", "data warehouse", "data factory",
        "synapse", "real-time analytics", "eventstream", "medallion",
        "delta lake", "spark", "dataflow",
    ],
    "foundry_iq": [
        "foundry", "ai foundry", "azure ai", "openai", "gpt", "llm",
        "rag", "retrieval augmented", "ai studio", "prompt flow",
        "cognitive services", "machine learning", "inference",
        "semantic kernel", "agent", "vector", "embedding",
    ],
}

AZURE_SERVICE_SIGNALS: dict[str, list[str]] = {
    "Azure AI Foundry": ["ai foundry", "azure ai foundry"],
    "Azure OpenAI Service": ["azure openai", "aoai", "gpt-4", "gpt4"],
    "Microsoft Fabric": ["microsoft fabric", "onelake", "fabric"],
    "Azure Kubernetes Service": ["aks", "kubernetes"],
    "Azure Container Apps": ["container apps"],
    "Azure Functions": ["azure functions", "serverless"],
    "Azure DevOps": ["azure devops"],
    "Azure Active Directory": ["entra id", "entra", "azure ad"],
    "Azure Monitor": ["azure monitor", "log analytics", "application insights"],
    "Azure Storage": ["blob storage", "azure storage"],
    "Azure SQL": ["azure sql", "sql database"],
    "Azure Cosmos DB": ["cosmos db", "cosmosdb"],
    "Azure Service Bus": ["service bus", "event grid", "event hub"],
    "Azure Networking": ["vnet", "expressroute", "private endpoint", "private link"],
    "Azure Security": ["defender", "sentinel", "key vault", "managed identity"],
    "Azure Bicep": ["bicep", "arm template"],
    "Azure Virtual Machines": ["virtual machine", "azure vm"],
    "Azure Arc": ["azure arc"],
    "Azure API Management": ["api management", "apim"],
    "Azure Cognitive Search": ["cognitive search", "ai search"],
    "GitHub Actions": ["github actions", "github copilot"],
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TechCommunityPost:
    """A single Tech Community blog post."""
    url: str
    title: str
    body_text: str              # Full article body, plain text
    author: str
    published_at: str           # ISO-8601 (best-effort)
    tags: list[str]             # Tags/categories from the post
    blog_section: str           # e.g. "azure-ai"
    iq_layers: list[str]
    azure_services: list[str]
    fingerprint: str            # SHA-256(url + title + body[:2048])
    source_type: str = "blog-post"
    crawled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TechCommunityCheckpoint:
    """Checkpoint state persisted between runs."""
    crawled_urls: list[str] = field(default_factory=list)
    last_seen_per_section: dict[str, str] = field(default_factory=dict)  # section → ISO-8601
    last_run: str | None = None
    total_processed: int = 0


# ---------------------------------------------------------------------------
# Tagging helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return text.lower()


def detect_iq_layers(title: str, body: str, tags: list[str]) -> list[str]:
    haystack = _normalise(f"{title} {body[:1000]} {' '.join(tags)}")
    matched = [
        layer for layer, signals in IQ_LAYER_SIGNALS.items()
        if any(sig in haystack for sig in signals)
    ]
    return matched or ["general"]


def detect_azure_services(title: str, body: str, tags: list[str]) -> list[str]:
    haystack = _normalise(f"{title} {body[:1000]} {' '.join(tags)}")
    return [
        svc for svc, signals in AZURE_SERVICE_SIGNALS.items()
        if any(sig in haystack for sig in signals)
    ]


def compute_fingerprint(url: str, title: str, body: str) -> str:
    """SHA-256(url + title + body[:2048])."""
    payload = f"{url}:{title}:{body[:2048]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------

def load_checkpoint(path: Path) -> TechCommunityCheckpoint:
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return TechCommunityCheckpoint(**data)
        except Exception as exc:
            logger.warning("Checkpoint load failed (%s): %s — starting fresh", path, exc)
    return TechCommunityCheckpoint()


def save_checkpoint(checkpoint: TechCommunityCheckpoint, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(checkpoint), indent=2))
    tmp.replace(path)
    logger.debug("Checkpoint saved → %s", path)


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def _extract_text(element: Tag | None) -> str:
    """Extract plain text from a BeautifulSoup element."""
    if element is None:
        return ""
    return element.get_text(separator=" ", strip=True)


def _resolve_url(href: str, base: str = BASE_URL) -> str:
    """Resolve relative URL against base."""
    if href.startswith("http"):
        return href
    return urljoin(base, href)


def _parse_iso_date(date_str: str) -> str:
    """
    Attempt to parse a date string into ISO-8601.
    Returns original string on failure.
    """
    # Try common formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return date_str.strip()


class TechCommunityParser:
    """
    Extracts structured data from Tech Community blog HTML.

    Tech Community uses Telligent Community / a custom React frontend.
    We target semantic elements (article, header, time, etc.) and fall
    back to heuristics when those are absent.
    """

    # Selectors to try for article body (most specific → most generic)
    BODY_SELECTORS = [
        "article.lia-message-body-content",
        "div.lia-message-body-content",
        'div[class*="article-body"]',
        'div[class*="post-body"]',
        'div[class*="blog-content"]',
        "main article",
        "article",
        "main",
    ]

    # Selectors for post listing pages
    POST_LINK_SELECTORS = [
        "a.lia-link-navigation.lia-page-link",
        'h2 a[href*="/blog/"]',
        'h3 a[href*="/blog/"]',
        'a[class*="post-title"]',
        'a[class*="article-title"]',
    ]

    def extract_post_links(self, html: str, base_url: str) -> list[str]:
        """Extract post detail URLs from a blog listing page."""
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        seen: set[str] = set()

        # Try specific selectors first
        for selector in self.POST_LINK_SELECTORS:
            anchors = soup.select(selector)
            for a in anchors:
                href = a.get("href", "")
                if href and "/blog/" in href and "/t5/" not in href:
                    full = _resolve_url(href, base_url)
                    if full not in seen:
                        seen.add(full)
                        links.append(full)

        # Fallback: any anchor whose href contains /blog/ and a slug
        if not links:
            for a in soup.find_all("a", href=True):
                href = str(a.get("href", ""))
                if re.search(r"/blog/[^/]+/[^/]+", href):
                    full = _resolve_url(href, base_url)
                    if full not in seen and "page" not in href:
                        seen.add(full)
                        links.append(full)

        return links

    def extract_next_page_url(self, html: str, base_url: str) -> str | None:
        """Extract the 'next page' URL from a listing page, if present."""
        soup = BeautifulSoup(html, "html.parser")

        # Common pagination patterns
        selectors = [
            "a[rel='next']",
            'a[aria-label="Next"]',
            'a[class*="next"]',
            'li.pagination-next a',
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                href = el.get("href", "")
                if href:
                    return _resolve_url(str(href), base_url)

        # Numbered pagination: find current page link and look for next number
        current = soup.select_one('li.pagination-current, span[aria-current="page"]')
        if current:
            try:
                current_num = int(re.sub(r"\D", "", current.get_text()))
                next_num = current_num + 1
                next_el = soup.find("a", string=str(next_num))
                if next_el:
                    href = next_el.get("href", "")
                    if href:
                        return _resolve_url(str(href), base_url)
            except (ValueError, TypeError):
                pass

        return None

    def parse_post(self, html: str, url: str, blog_section: str) -> TechCommunityPost | None:
        """Parse a full article page into a TechCommunityPost."""
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title = ""
        for sel in ["h1.lia-thread-subject", "h1.entry-title", "h1.post-title", "h1"]:
            el = soup.select_one(sel)
            if el:
                title = _extract_text(el)
                break

        if not title:
            # Try OG tags
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = str(og_title.get("content", ""))

        if not title:
            logger.debug("No title found for %s — skipping", url)
            return None

        # Body text
        body_text = ""
        for sel in self.BODY_SELECTORS:
            el = soup.select_one(sel)
            if el:
                # Remove script/style noise
                for tag in el.find_all(["script", "style", "nav", "footer"]):
                    tag.decompose()
                body_text = _extract_text(el)
                if len(body_text) > 200:
                    break

        if not body_text:
            # Final fallback: strip entire page
            for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            body_text = soup.get_text(separator=" ", strip=True)

        # Author
        author = ""
        for sel in [
            'span[class*="author"]',
            'a[class*="author"]',
            'meta[name="author"]',
            'span.UserName',
        ]:
            el = soup.select_one(sel)
            if el:
                author = (
                    str(el.get("content", "")) if el.name == "meta"
                    else _extract_text(el)
                )
                if author:
                    break

        # Published date
        published_at = ""
        for sel in ["time[datetime]", "time", 'meta[property="article:published_time"]', 'span[class*="date"]']:
            el = soup.select_one(sel)
            if el:
                raw = (
                    str(el.get("datetime", "") or el.get("content", ""))
                    if el.name in ("time", "meta")
                    else _extract_text(el)
                )
                if raw:
                    published_at = _parse_iso_date(raw)
                    break

        # Tags
        tags: list[str] = []
        for sel in [
            'a[class*="tag"]',
            'a[rel="tag"]',
            'span[class*="tag"]',
            'li[class*="tag"] a',
        ]:
            els = soup.select(sel)
            if els:
                tags = [_extract_text(t) for t in els if _extract_text(t)]
                break

        fingerprint = compute_fingerprint(url, title, body_text)
        iq_layers = detect_iq_layers(title, body_text, tags)
        azure_services = detect_azure_services(title, body_text, tags)

        return TechCommunityPost(
            url=url,
            title=title,
            body_text=body_text,
            author=author,
            published_at=published_at or datetime.now(timezone.utc).isoformat(),
            tags=tags,
            blog_section=blog_section,
            iq_layers=iq_layers,
            azure_services=azure_services,
            fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# HTTP client wrapper with rate limiting
# ---------------------------------------------------------------------------

class ThrottledHTTPClient:
    """
    Async HTTP client with concurrency limiting and per-request delay.

    - max_concurrent: semaphore limit (default 3)
    - delay_seconds: sleep after each request (default 2.0)
    """

    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT,
        delay_seconds: float = REQUEST_DELAY_SECONDS,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._delay = delay_seconds
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    async def get(self, url: str) -> str | None:
        """Fetch URL, returning response text or None on error."""
        async with self._semaphore:
            try:
                response = await self._client.get(url)
                response.raise_for_status()
                await asyncio.sleep(self._delay)
                return response.text
            except httpx.HTTPStatusError as exc:
                logger.warning("HTTP %d for %s", exc.response.status_code, url)
            except httpx.RequestError as exc:
                logger.warning("Request error for %s: %s", url, exc)
            return None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ThrottledHTTPClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()


# ---------------------------------------------------------------------------
# Main crawler
# ---------------------------------------------------------------------------

class TechCommunityCrawler:
    """
    Crawls three Microsoft Tech Community blog sections.

    Fetches listing pages, discovers post URLs, parses each post, and yields
    TechCommunityPost records.  Skips already-crawled URLs (checkpoint).

    Usage::

        crawler = TechCommunityCrawler()
        posts = await crawler.crawl_all()
    """

    def __init__(
        self,
        entry_points: list[dict[str, str]] | None = None,
        checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
        max_pages_per_blog: int = MAX_PAGES_PER_BLOG,
        max_concurrent: int = MAX_CONCURRENT,
        delay_seconds: float = REQUEST_DELAY_SECONDS,
    ) -> None:
        self.entry_points = entry_points or BLOG_ENTRY_POINTS
        self.checkpoint_path = Path(checkpoint_path)
        self.max_pages_per_blog = max_pages_per_blog
        self.max_concurrent = max_concurrent
        self.delay_seconds = delay_seconds
        self._parser = TechCommunityParser()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def crawl_all(self) -> list[dict[str, Any]]:
        """Return all new posts as a list of dicts."""
        results: list[dict[str, Any]] = []
        async for post in self.crawl():
            results.append(asdict(post))
        return results

    async def crawl(self):  # noqa: ANN201 — yields TechCommunityPost
        """Async generator that yields new TechCommunityPost records."""
        checkpoint = load_checkpoint(self.checkpoint_path)
        crawled_set = set(checkpoint.crawled_urls)
        total = 0

        async with ThrottledHTTPClient(
            max_concurrent=self.max_concurrent,
            delay_seconds=self.delay_seconds,
        ) as http:
            for entry in self.entry_points:
                blog_url = entry["url"]
                label = entry["label"]
                logger.info("Crawling blog section: %s (%s)", label, blog_url)

                async for post in self._crawl_section(http, blog_url, label, crawled_set):
                    checkpoint.crawled_urls.append(post.url)
                    crawled_set.add(post.url)
                    checkpoint.total_processed += 1
                    total += 1
                    save_checkpoint(checkpoint, self.checkpoint_path)
                    yield post

        checkpoint.last_run = datetime.now(timezone.utc).isoformat()
        save_checkpoint(checkpoint, self.checkpoint_path)
        logger.info("Tech Community crawl complete — %d new posts.", total)

    # ------------------------------------------------------------------
    # Section crawler
    # ------------------------------------------------------------------

    async def _crawl_section(
        self,
        http: ThrottledHTTPClient,
        start_url: str,
        label: str,
        already_crawled: set[str],
    ):  # noqa: ANN201 — yields TechCommunityPost
        """Paginate through a blog section and crawl new posts."""
        listing_url: str | None = start_url
        page = 0

        while listing_url and page < self.max_pages_per_blog:
            logger.info("  Listing page %d: %s", page + 1, listing_url)
            html = await http.get(listing_url)
            if not html:
                break

            post_links = self._parser.extract_post_links(html, listing_url)
            logger.info("  Found %d post links on page %d", len(post_links), page + 1)

            # Filter to new posts
            new_links = [u for u in post_links if u not in already_crawled]
            if not new_links:
                logger.info("  No new posts on page %d — stopping section crawl", page + 1)
                break

            # Crawl posts concurrently (bounded by ThrottledHTTPClient semaphore)
            tasks = [self._crawl_post(http, url, label) for url in new_links]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Post crawl error: %s", result)
                elif result is not None:
                    logger.info(
                        "    ✓ %s | layers=%s | services=%d",
                        result.title[:60],
                        result.iq_layers,
                        len(result.azure_services),
                    )
                    yield result

            # Advance to next page
            next_url = self._parser.extract_next_page_url(html, listing_url)
            listing_url = next_url
            page += 1

    async def _crawl_post(
        self,
        http: ThrottledHTTPClient,
        url: str,
        blog_section: str,
    ) -> TechCommunityPost | None:
        """Fetch and parse a single post page."""
        html = await http.get(url)
        if not html:
            return None
        try:
            return self._parser.parse_post(html, url, blog_section)
        except Exception as exc:
            logger.warning("Parse error for %s: %s", url, exc)
            return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    import argparse

    parser = argparse.ArgumentParser(description="Crawl Microsoft Tech Community blogs")
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT_PATH))
    parser.add_argument("--output", default="techcommunity_posts.json")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES_PER_BLOG)
    args = parser.parse_args()

    crawler = TechCommunityCrawler(
        checkpoint_path=Path(args.checkpoint),
        max_pages_per_blog=args.max_pages,
    )
    posts = await crawler.crawl_all()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(posts, indent=2))
    logger.info("Wrote %d posts to %s", len(posts), output_path)


if __name__ == "__main__":
    asyncio.run(_main())
