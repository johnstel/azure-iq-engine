"""
Azure Updates Crawler — https://azure.microsoft.com/en-us/updates/feed/

Parses the Azure Updates RSS/Atom feed, extracts each announcement, and tags
it with IQ layers and Azure services.  Posts are flagged `atomic` because
they are short enough to index as a single chunk (no splitting needed).

Checkpoint: persists the latest published datetime seen so re-runs only
process new entries (deduplication by fingerprint = SHA256(url + title + summary)).

Dependencies:
    pip install httpx feedparser
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AZURE_UPDATES_FEED = "https://azure.microsoft.com/en-us/updates/feed/"
DEFAULT_CHECKPOINT_PATH = Path("checkpoints/azure_updates_checkpoint.json")
REQUEST_TIMEOUT = 30.0
USER_AGENT = "AzureIQEngine-Crawler/1.0 (+https://github.com/azure-iq-engine)"

# IQ layer keyword mapping (shared pattern with youtube_crawler)
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
    "Azure OpenAI Service": ["azure openai", "aoai", "gpt-4", "gpt-3", "gpt4"],
    "Microsoft Fabric": ["microsoft fabric", "fabric iq", "onelake", "fabric"],
    "Azure Kubernetes Service": ["aks", "kubernetes", "k8s"],
    "Azure Container Apps": ["container apps", "aca"],
    "Azure Functions": ["azure functions", "function app", "serverless"],
    "Azure DevOps": ["azure devops", "devops pipeline"],
    "Azure Active Directory": ["azure ad", "entra id", "entra"],
    "Azure Monitor": ["azure monitor", "log analytics", "application insights"],
    "Azure Storage": ["blob storage", "azure storage", "storage account"],
    "Azure SQL": ["azure sql", "sql database", "sql managed instance"],
    "Azure Cosmos DB": ["cosmos db", "cosmosdb"],
    "Azure Service Bus": ["service bus", "event grid", "event hub"],
    "Azure Networking": ["vnet", "expressroute", "vpn gateway", "private endpoint", "private link"],
    "Azure Security": ["defender", "sentinel", "security center", "key vault", "managed identity"],
    "Azure Bicep": ["bicep", "arm template", "infrastructure as code"],
    "Azure Virtual Machines": ["virtual machine", "azure vm", "azure vmss"],
    "Azure Arc": ["azure arc"],
    "Azure Load Balancer": ["load balancer", "application gateway", "front door", "traffic manager"],
    "Azure API Management": ["api management", "apim"],
    "Azure Cognitive Search": ["cognitive search", "azure search", "ai search"],
    "Azure Container Registry": ["container registry", "acr"],
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AzureUpdate:
    """A single Azure Update post."""
    url: str
    title: str
    summary: str                    # Raw HTML or plain text summary
    published_at: str               # ISO-8601
    categories: list[str]           # Tags from RSS <category> elements
    iq_layers: list[str]
    azure_services: list[str]
    fingerprint: str                # SHA-256(url + title + summary)
    content_type: str = "atomic"    # Never chunked
    source_type: str = "azure-update"
    crawled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class UpdatesCheckpoint:
    """Persisted checkpoint for the Azure Updates crawler."""
    last_seen_published_at: str | None = None  # ISO-8601 of newest entry seen
    processed_fingerprints: list[str] = field(default_factory=list)
    last_run: str | None = None
    total_processed: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return text.lower()


def _strip_html(html: str) -> str:
    """Naive HTML tag stripper for summary text."""
    return re.sub(r"<[^>]+>", " ", html).strip()


def _parse_rfc2822(date_str: str) -> datetime:
    """Parse RFC-2822 date string to timezone-aware datetime."""
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(timezone.utc)


def detect_iq_layers(title: str, summary: str, categories: list[str]) -> list[str]:
    haystack = _normalise(f"{title} {summary} {' '.join(categories)}")
    matched = [
        layer for layer, signals in IQ_LAYER_SIGNALS.items()
        if any(sig in haystack for sig in signals)
    ]
    return matched or ["general"]


def detect_azure_services(title: str, summary: str, categories: list[str]) -> list[str]:
    haystack = _normalise(f"{title} {summary} {' '.join(categories)}")
    return [
        service for service, signals in AZURE_SERVICE_SIGNALS.items()
        if any(sig in haystack for sig in signals)
    ]


def compute_fingerprint(url: str, title: str, summary: str) -> str:
    """SHA-256(url + title + summary)."""
    payload = f"{url}:{title}:{summary}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------

def load_checkpoint(path: Path) -> UpdatesCheckpoint:
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return UpdatesCheckpoint(**data)
        except Exception as exc:
            logger.warning("Checkpoint load failed (%s): %s — starting fresh", path, exc)
    return UpdatesCheckpoint()


def save_checkpoint(checkpoint: UpdatesCheckpoint, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(checkpoint), indent=2))
    tmp.replace(path)
    logger.debug("Checkpoint saved → %s", path)


# ---------------------------------------------------------------------------
# Feed parser
# ---------------------------------------------------------------------------

def _parse_feed(raw_xml: str) -> list[dict[str, Any]]:
    """
    Parse RSS/Atom XML using feedparser.

    Returns a list of raw entry dicts.  feedparser is a pure-Python library
    with no external dependencies and handles malformed feeds gracefully.
    """
    try:
        import feedparser  # type: ignore
    except ImportError as exc:
        raise ImportError("feedparser is required — pip install feedparser") from exc

    feed = feedparser.parse(raw_xml)
    if feed.bozo and feed.bozo_exception:
        logger.warning("Feed parse warning: %s", feed.bozo_exception)
    return feed.entries  # type: ignore[return-value]


def _entry_to_update(entry: Any) -> AzureUpdate:
    """Convert a feedparser entry to an AzureUpdate record."""
    url: str = getattr(entry, "link", "") or ""
    title: str = getattr(entry, "title", "") or ""

    # Summary may be HTML; store plain text version
    raw_summary: str = getattr(entry, "summary", "") or ""
    summary = _strip_html(raw_summary)

    # Published date
    published_parsed = getattr(entry, "published_parsed", None)
    if published_parsed:
        published_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
    else:
        published_raw = getattr(entry, "published", "")
        published_dt = _parse_rfc2822(published_raw) if published_raw else datetime.now(timezone.utc)
    published_at = published_dt.isoformat()

    # Categories / tags
    tags_raw = getattr(entry, "tags", []) or []
    categories: list[str] = [
        tag.get("term", "") or tag.get("label", "")
        for tag in tags_raw
        if isinstance(tag, dict)
    ]
    categories = [c for c in categories if c]

    fingerprint = compute_fingerprint(url, title, summary)
    iq_layers = detect_iq_layers(title, summary, categories)
    azure_services = detect_azure_services(title, summary, categories)

    return AzureUpdate(
        url=url,
        title=title,
        summary=summary,
        published_at=published_at,
        categories=categories,
        iq_layers=iq_layers,
        azure_services=azure_services,
        fingerprint=fingerprint,
    )


# ---------------------------------------------------------------------------
# Main crawler
# ---------------------------------------------------------------------------

class AzureUpdatesCrawler:
    """
    Parses the Azure Updates RSS feed and yields new AzureUpdate records.

    Incremental mode: only entries newer than checkpoint.last_seen_published_at
    (or not already fingerprinted) are yielded.

    Usage::

        crawler = AzureUpdatesCrawler()
        updates = await crawler.crawl_all()
    """

    def __init__(
        self,
        feed_url: str = AZURE_UPDATES_FEED,
        checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
        full_refresh: bool = False,
    ) -> None:
        self.feed_url = feed_url
        self.checkpoint_path = Path(checkpoint_path)
        self.full_refresh = full_refresh

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def crawl_all(self) -> list[dict[str, Any]]:
        """Return all new updates as a list of dicts."""
        results: list[dict[str, Any]] = []
        async for update in self.crawl():
            results.append(asdict(update))
        return results

    async def crawl(self):  # noqa: ANN201 — yields AzureUpdate
        """Async generator yielding new AzureUpdate records."""
        checkpoint = load_checkpoint(self.checkpoint_path)
        seen_fps = set(checkpoint.processed_fingerprints)

        # Parse cutoff date for incremental mode
        cutoff_dt: datetime | None = None
        if not self.full_refresh and checkpoint.last_seen_published_at:
            try:
                cutoff_dt = datetime.fromisoformat(checkpoint.last_seen_published_at)
                logger.info("Incremental mode — skipping entries at or before %s", cutoff_dt.isoformat())
            except ValueError:
                pass

        # Fetch feed
        raw_xml = await self._fetch_feed()
        if not raw_xml:
            return

        entries = _parse_feed(raw_xml)
        logger.info("Feed returned %d entries", len(entries))

        newest_dt: datetime | None = None
        count = 0

        for entry in entries:
            update = _entry_to_update(entry)

            # Skip already-seen fingerprints
            if update.fingerprint in seen_fps:
                logger.debug("Skip (already seen): %s", update.title[:60])
                continue

            # Skip entries older than or equal to cutoff
            if cutoff_dt:
                entry_dt = datetime.fromisoformat(update.published_at)
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                cutoff_aware = cutoff_dt if cutoff_dt.tzinfo else cutoff_dt.replace(tzinfo=timezone.utc)
                if entry_dt <= cutoff_aware:
                    logger.debug("Skip (too old): %s", update.title[:60])
                    continue

            # Track newest published date
            entry_dt = datetime.fromisoformat(update.published_at)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            if newest_dt is None or entry_dt > newest_dt:
                newest_dt = entry_dt

            seen_fps.add(update.fingerprint)
            checkpoint.processed_fingerprints.append(update.fingerprint)
            checkpoint.total_processed += 1
            count += 1

            logger.info(
                "[%d] %s | %s | layers=%s",
                count,
                update.published_at[:10],
                update.title[:70],
                update.iq_layers,
            )
            yield update

        # Persist checkpoint
        if newest_dt:
            checkpoint.last_seen_published_at = newest_dt.isoformat()
        checkpoint.last_run = datetime.now(timezone.utc).isoformat()
        save_checkpoint(checkpoint, self.checkpoint_path)
        logger.info("Done — %d new updates processed.", count)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_feed(self) -> str | None:
        """Fetch the raw RSS/Atom XML from the feed URL."""
        headers = {"User-Agent": USER_AGENT}
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(self.feed_url, headers=headers)
                response.raise_for_status()
                logger.info("Feed fetched: %s bytes", len(response.content))
                return response.text
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP error fetching feed: %s", exc)
        except httpx.RequestError as exc:
            logger.error("Request error fetching feed: %s", exc)
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

    parser = argparse.ArgumentParser(description="Crawl Azure Updates RSS feed")
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT_PATH))
    parser.add_argument("--output", default="azure_updates.json")
    parser.add_argument("--full-refresh", action="store_true", help="Ignore checkpoint, fetch all")
    args = parser.parse_args()

    crawler = AzureUpdatesCrawler(
        checkpoint_path=Path(args.checkpoint),
        full_refresh=args.full_refresh,
    )
    updates = await crawler.crawl_all()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(updates, indent=2))
    logger.info("Wrote %d updates to %s", len(updates), output_path)


if __name__ == "__main__":
    asyncio.run(_main())
