"""
Azure411 Blog Crawler — https://www.azure411.com/rss/

Parses John Stelmaszek's Azure411 Ghost blog via its RSS feed.
Each post is returned as a document with full HTML-stripped body text,
categories, and metadata suitable for the IQ Engine ingestion pipeline.

Checkpoint: persists the latest published datetime so re-runs only
process new entries.

Dependencies:
    pip install httpx feedparser beautifulsoup4
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AZURE411_RSS = "https://www.azure411.com/rss/"
DEFAULT_CHECKPOINT_PATH = Path("checkpoints/azure411_checkpoint.json")
REQUEST_TIMEOUT = 30.0
USER_AGENT = "AzureIQEngine-Crawler/1.0 (+https://github.com/azure-iq-engine)"

IQ_LAYER_SIGNALS: dict[str, list[str]] = {
    "work_iq": [
        "copilot", "m365", "microsoft 365", "teams", "viva", "sharepoint",
        "power platform", "power automate", "power apps", "power bi",
        "productivity", "workplace",
    ],
    "fabric_iq": [
        "fabric", "onelake", "lakehouse", "data warehouse", "data factory",
        "synapse", "real-time analytics", "eventstream", "medallion",
        "delta lake", "spark", "dataflow", "fabric iq",
    ],
    "foundry_iq": [
        "foundry", "ai foundry", "azure ai", "openai", "gpt", "llm",
        "rag", "retrieval augmented", "ai studio", "prompt flow",
        "cognitive services", "machine learning", "inference",
        "semantic kernel", "agent", "vector", "embedding", "foundry iq",
    ],
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BlogPost:
    """A single Azure411 blog post."""

    title: str
    url: str
    published_at: str  # ISO 8601
    author: str
    categories: list[str]
    body_text: str  # HTML-stripped full text
    summary: str  # RSS <description>
    fingerprint: str  # SHA-256(url + title + body[:2048])
    source_type: str = "blog-post"
    iq_layers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def _load_checkpoint(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_published": None, "crawled_urls": []}


def _save_checkpoint(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_iq_layers(text: str) -> list[str]:
    lower = text.lower()
    return sorted({
        layer for layer, keywords in IQ_LAYER_SIGNALS.items()
        if any(kw in lower for kw in keywords)
    })


def _strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def _fingerprint(url: str, title: str, body: str) -> str:
    raw = f"{url}|{title}|{body[:2048]}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

class Azure411Crawler:
    """Fetch Azure411 blog posts via RSS."""

    def __init__(
        self,
        checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
        full_refresh: bool = False,
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.full_refresh = full_refresh

    async def crawl_all(self) -> list[dict[str, Any]]:
        import feedparser

        checkpoint = _load_checkpoint(self.checkpoint_path)
        last_pub = checkpoint.get("last_published")
        crawled_urls: set[str] = set(checkpoint.get("crawled_urls", []))

        logger.info("Fetching Azure411 RSS feed: %s", AZURE411_RSS)

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                AZURE411_RSS,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        entries = feed.get("entries", [])
        logger.info("Found %d entries in Azure411 RSS feed.", len(entries))

        posts: list[BlogPost] = []
        newest_pub: str | None = last_pub

        for entry in entries:
            url = entry.get("link", "")
            if not url:
                continue

            # Skip already-crawled posts unless full refresh
            if not self.full_refresh and url in crawled_urls:
                continue

            title = entry.get("title", "Untitled")

            # Parse published date
            pub_str = entry.get("published", "")
            try:
                pub_dt = parsedate_to_datetime(pub_str)
                iso_pub = pub_dt.isoformat()
            except Exception:
                iso_pub = pub_str
                pub_dt = None

            # Skip old posts unless full refresh
            if not self.full_refresh and last_pub and iso_pub and iso_pub <= last_pub:
                continue

            # Extract body text from content:encoded
            body_html = ""
            if entry.get("content"):
                body_html = entry["content"][0].get("value", "")
            elif entry.get("summary"):
                body_html = entry["summary"]

            body_text = _strip_html(body_html)
            summary = entry.get("summary", "")[:500]

            # Categories
            categories = [t.get("term", "") for t in entry.get("tags", [])]

            # Author
            author = entry.get("author", "John Stelmaszek")

            fp = _fingerprint(url, title, body_text)
            iq_layers = _detect_iq_layers(body_text + " " + " ".join(categories))

            post = BlogPost(
                title=title,
                url=url,
                published_at=iso_pub,
                author=author,
                categories=categories,
                body_text=body_text,
                summary=summary,
                fingerprint=fp,
                iq_layers=iq_layers,
            )
            posts.append(post)
            crawled_urls.add(url)

            if newest_pub is None or (iso_pub and iso_pub > newest_pub):
                newest_pub = iso_pub

        # Save checkpoint
        _save_checkpoint(
            {
                "last_published": newest_pub,
                "crawled_urls": sorted(crawled_urls),
            },
            self.checkpoint_path,
        )

        logger.info("Azure411 crawl complete: %d new posts.", len(posts))
        return [p.to_dict() for p in posts]
