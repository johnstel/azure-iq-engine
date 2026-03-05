"""
YouTube Crawler — John Savill's Technical Training (UCpIn7ox7j7bH_OFj7tYouOQ).

Fetches full video catalog via YouTube Data API v3, extracts transcripts via
youtube-transcript-api (zero quota cost), and tags each video with IQ layers
and Azure services based on title + description analysis.

Checkpoint/resume: progress is saved to a JSON sidecar file so re-runs skip
already-processed videos.  SHA-256 fingerprint = hash(video_id + transcript).

Environment:
    YOUTUBE_API_KEY  — YouTube Data API v3 key (optional; skips catalog fetch
                       if absent, falls back to checkpoint data only)

Dependencies:
    pip install google-api-python-client youtube-transcript-api httpx
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAVILL_CHANNEL_ID = "UCpIn7ox7j7bH_OFj7tYouOQ"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
MAX_RESULTS_PER_PAGE = 50  # YouTube API max

# IQ layer keyword mapping
IQ_LAYER_SIGNALS: dict[str, list[str]] = {
    "work_iq": [
        "copilot", "m365", "microsoft 365", "teams", "viva", "sharepoint",
        "power platform", "power automate", "power apps", "power bi",
        "productivity", "workplace", "employee experience",
    ],
    "fabric_iq": [
        "fabric", "onelake", "lakehouse", "data warehouse", "data factory",
        "synapse", "real-time analytics", "eventstream", "medallion",
        "delta lake", "spark", "dataflow", "pipeline",
    ],
    "foundry_iq": [
        "foundry", "ai foundry", "azure ai", "openai", "gpt", "llm",
        "rag", "retrieval augmented", "ai studio", "prompt flow",
        "cognitive services", "machine learning", "ml", "inference",
        "semantic kernel", "agent", "vector", "embedding",
    ],
}

# Azure service keyword mapping (ordered from most specific to most generic)
AZURE_SERVICE_SIGNALS: dict[str, list[str]] = {
    "Azure AI Foundry": ["ai foundry", "azure ai foundry", "foundry"],
    "Azure OpenAI Service": ["azure openai", "aoai", "gpt-4", "gpt-3", "gpt4"],
    "Microsoft Fabric": ["microsoft fabric", "fabric iq", "onelake", "fabric"],
    "Azure Kubernetes Service": ["aks", "kubernetes", "k8s"],
    "Azure Container Apps": ["container apps", "aca"],
    "Azure Functions": ["azure functions", "function app", "serverless"],
    "Azure DevOps": ["azure devops", "ado", "devops"],
    "Azure Active Directory": ["azure ad", "aad", "entra id", "entra"],
    "Azure Monitor": ["azure monitor", "log analytics", "application insights"],
    "Azure Storage": ["blob storage", "azure storage", "storage account"],
    "Azure SQL": ["azure sql", "sql database", "sql managed"],
    "Azure Cosmos DB": ["cosmos db", "cosmosdb"],
    "Azure Service Bus": ["service bus", "event grid", "event hub", "eventhub"],
    "Azure Networking": ["vnet", "virtual network", "expressroute", "vpn gateway", "private endpoint"],
    "Azure Security": ["defender", "sentinel", "security center", "key vault", "managed identity"],
    "Azure Bicep": ["bicep", "arm template", "infrastructure as code", "iac"],
    "Azure Virtual Machines": ["virtual machine", "azure vm", "hyper-v"],
    "Azure Arc": ["azure arc", "arc-enabled"],
    "GitHub Actions": ["github actions", "ci/cd", "github copilot"],
    "Azure Load Balancer": ["load balancer", "application gateway", "front door"],
}

DEFAULT_CHECKPOINT_PATH = Path("checkpoints/youtube_crawler_checkpoint.json")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class VideoMetadata:
    """Normalised video record with transcript and tags."""
    video_id: str
    title: str
    description: str
    published_at: str           # ISO-8601
    duration_iso: str           # ISO-8601 duration from API
    view_count: int
    channel_id: str
    channel_title: str
    transcript_text: str        # Full concatenated transcript
    transcript_language: str
    transcript_segments: list[dict[str, Any]] = field(default_factory=list)  # [{text, start, duration}]
    iq_layers: list[str]        # e.g. ["foundry_iq", "fabric_iq"]
    azure_services: list[str]   # e.g. ["Azure OpenAI Service", "Microsoft Fabric"]
    fingerprint: str            # SHA-256(video_id + transcript_text)
    source_type: str = "video-transcript"
    crawled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CrawlerCheckpoint:
    """Persisted progress state for checkpoint/resume."""
    processed_video_ids: list[str] = field(default_factory=list)
    next_page_token: str | None = None
    last_run: str | None = None
    total_processed: int = 0


# ---------------------------------------------------------------------------
# Tagging helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return text.lower()


def detect_iq_layers(title: str, description: str) -> list[str]:
    """Return IQ layers present in title + description."""
    haystack = _normalise(f"{title} {description}")
    matched: list[str] = []
    for layer, signals in IQ_LAYER_SIGNALS.items():
        if any(sig in haystack for sig in signals):
            matched.append(layer)
    return matched or ["general"]


def detect_azure_services(title: str, description: str) -> list[str]:
    """Return Azure service names mentioned in title + description."""
    haystack = _normalise(f"{title} {description}")
    matched: list[str] = []
    for service, signals in AZURE_SERVICE_SIGNALS.items():
        if any(sig in haystack for sig in signals):
            matched.append(service)
    return matched


def compute_fingerprint(video_id: str, transcript_text: str) -> str:
    """SHA-256 of video_id + transcript_text."""
    payload = f"{video_id}:{transcript_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Checkpoint persistence
# ---------------------------------------------------------------------------

def load_checkpoint(path: Path) -> CrawlerCheckpoint:
    """Load checkpoint from disk; return empty checkpoint if not found."""
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return CrawlerCheckpoint(**data)
        except Exception as exc:
            logger.warning("Failed to load checkpoint from %s: %s — starting fresh", path, exc)
    return CrawlerCheckpoint()


def save_checkpoint(checkpoint: CrawlerCheckpoint, path: Path) -> None:
    """Persist checkpoint to disk atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(checkpoint), indent=2))
    tmp.replace(path)
    logger.debug("Checkpoint saved → %s (%d videos)", path, checkpoint.total_processed)


# ---------------------------------------------------------------------------
# Transcript extraction
# ---------------------------------------------------------------------------

async def _fetch_transcript(video_id: str) -> tuple[str, str, list[dict[str, Any]]]:
    """
    Fetch transcript for a video using youtube-transcript-api.

    Returns (transcript_text, language_code, segments).
    segments = list of {"text": str, "start": float, "duration": float}.
    Falls back to empty on failure.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore

        loop = asyncio.get_running_loop()

        def _fetch() -> tuple[str, str, list[dict[str, Any]]]:
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
            segments = [
                {"text": s.text, "start": s.start, "duration": s.duration}
                for s in transcript.snippets
            ]
            text = " ".join(s.text for s in transcript.snippets)
            return text, transcript.language_code or "en", segments

        text, lang, segments = await loop.run_in_executor(None, _fetch)
        return text, lang, segments

    except ImportError:
        logger.error("youtube-transcript-api not installed — pip install youtube-transcript-api")
        return "", "unknown", []
    except Exception as exc:
        logger.debug("No transcript for %s: %s", video_id, exc)
        return "", "unknown", []


# ---------------------------------------------------------------------------
# YouTube Data API helpers (httpx, no googleapis client required)
# ---------------------------------------------------------------------------

async def _api_get(client: httpx.AsyncClient, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """Perform a single YouTube API GET with error handling."""
    response = await client.get(f"{YOUTUBE_API_BASE}/{endpoint}", params=params)
    response.raise_for_status()
    return response.json()


async def _fetch_playlist_items(
    client: httpx.AsyncClient,
    api_key: str,
    uploads_playlist_id: str,
    page_token: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one page of playlist items. Returns (items, next_page_token)."""
    params: dict[str, Any] = {
        "key": api_key,
        "part": "snippet,contentDetails",
        "playlistId": uploads_playlist_id,
        "maxResults": MAX_RESULTS_PER_PAGE,
    }
    if page_token:
        params["pageToken"] = page_token

    data = await _api_get(client, "playlistItems", params)
    items = data.get("items", [])
    next_token = data.get("nextPageToken")
    return items, next_token


async def _fetch_video_details(
    client: httpx.AsyncClient,
    api_key: str,
    video_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Fetch contentDetails + statistics for up to 50 video IDs.
    Returns dict keyed by video_id.
    """
    params = {
        "key": api_key,
        "part": "contentDetails,statistics,snippet",
        "id": ",".join(video_ids),
    }
    data = await _api_get(client, "videos", params)
    return {item["id"]: item for item in data.get("items", [])}


async def _resolve_uploads_playlist(
    client: httpx.AsyncClient,
    api_key: str,
    channel_id: str,
) -> str:
    """Resolve the uploads playlist ID for a channel."""
    params = {
        "key": api_key,
        "part": "contentDetails",
        "id": channel_id,
    }
    data = await _api_get(client, "channels", params)
    items = data.get("items", [])
    if not items:
        raise ValueError(f"Channel not found: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


# ---------------------------------------------------------------------------
# Main crawler
# ---------------------------------------------------------------------------

class YouTubeCrawler:
    """
    Crawls John Savill's YouTube channel.

    Usage::

        crawler = YouTubeCrawler()
        async for video in crawler.crawl():
            process(video)

    Or collect all at once::

        videos = await crawler.crawl_all()
    """

    def __init__(
        self,
        channel_id: str = SAVILL_CHANNEL_ID,
        api_key: str | None = None,
        checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
        max_videos: int | None = None,
        transcript_concurrency: int = 5,
    ) -> None:
        self.channel_id = channel_id
        self.api_key: str | None = api_key or os.getenv("YOUTUBE_API_KEY")
        self.checkpoint_path = Path(checkpoint_path)
        self.max_videos = max_videos
        self.transcript_semaphore = asyncio.Semaphore(transcript_concurrency)

        if not self.api_key:
            logger.warning(
                "YOUTUBE_API_KEY not set — catalog fetch will be skipped. "
                "Existing checkpoint data will still be available."
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def crawl_all(self) -> list[dict[str, Any]]:
        """Crawl all videos and return as a list of dicts."""
        results: list[dict[str, Any]] = []
        async for video in self.crawl():
            results.append(asdict(video))
        return results

    async def crawl(self):  # noqa: ANN201  — yields VideoMetadata
        """
        Async generator that yields VideoMetadata for each unprocessed video.

        Saves checkpoint after every page of results so progress is preserved
        even if the process is interrupted mid-run.
        """
        checkpoint = load_checkpoint(self.checkpoint_path)
        processed_set = set(checkpoint.processed_video_ids)

        if not self.api_key:
            logger.warning("No API key — nothing to crawl. Yielding nothing.")
            return

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Resolve the uploads playlist
            try:
                uploads_playlist_id = await _resolve_uploads_playlist(
                    client, self.api_key, self.channel_id
                )
                logger.info("Uploads playlist: %s", uploads_playlist_id)
            except Exception as exc:
                logger.error("Failed to resolve uploads playlist: %s", exc)
                return

            page_token = checkpoint.next_page_token
            total_yielded = 0

            # 2. Paginate through playlist
            while True:
                if self.max_videos and total_yielded >= self.max_videos:
                    logger.info("Reached max_videos=%d — stopping.", self.max_videos)
                    break

                try:
                    items, next_page_token = await _fetch_playlist_items(
                        client, self.api_key, uploads_playlist_id, page_token
                    )
                except Exception as exc:
                    logger.error("Playlist fetch error (token=%s): %s", page_token, exc)
                    break

                if not items:
                    break

                # Filter already-processed
                new_items = [
                    item for item in items
                    if item["contentDetails"]["videoId"] not in processed_set
                ]

                if new_items:
                    video_ids = [item["contentDetails"]["videoId"] for item in new_items]

                    # 3. Batch-fetch video details (statistics, duration)
                    try:
                        details_map = await _fetch_video_details(client, self.api_key, video_ids)
                    except Exception as exc:
                        logger.error("Video details fetch failed: %s", exc)
                        details_map = {}

                    # 4. Fetch transcripts concurrently
                    transcript_tasks = [
                        self._fetch_transcript_guarded(vid) for vid in video_ids
                    ]
                    transcripts: list[tuple[str, str, list[dict[str, Any]]]] = await asyncio.gather(*transcript_tasks)

                    # 5. Assemble records and yield
                    for item, (transcript_text, lang, segments) in zip(new_items, transcripts):
                        video_id = item["contentDetails"]["videoId"]
                        snippet = item.get("snippet", {})
                        detail = details_map.get(video_id, {})
                        stats = detail.get("statistics", {})
                        content_details = detail.get("contentDetails", {})

                        title = snippet.get("title", "")
                        description = snippet.get("description", "")
                        published_at = snippet.get("publishedAt", "")
                        channel_title = snippet.get("channelTitle", "")
                        duration_iso = content_details.get("duration", "PT0S")
                        view_count = int(stats.get("viewCount", 0))

                        iq_layers = detect_iq_layers(title, description)
                        azure_services = detect_azure_services(title, description)
                        fingerprint = compute_fingerprint(video_id, transcript_text)

                        video = VideoMetadata(
                            video_id=video_id,
                            title=title,
                            description=description,
                            published_at=published_at,
                            duration_iso=duration_iso,
                            view_count=view_count,
                            channel_id=self.channel_id,
                            channel_title=channel_title,
                            transcript_text=transcript_text,
                            transcript_language=lang,
                            transcript_segments=segments,
                            iq_layers=iq_layers,
                            azure_services=azure_services,
                            fingerprint=fingerprint,
                        )

                        processed_set.add(video_id)
                        checkpoint.processed_video_ids.append(video_id)
                        checkpoint.total_processed += 1
                        total_yielded += 1

                        logger.info(
                            "[%d] %s | layers=%s | services=%d | transcript=%d chars",
                            total_yielded,
                            title[:60],
                            iq_layers,
                            len(azure_services),
                            len(transcript_text),
                        )

                        yield video

                        if self.max_videos and total_yielded >= self.max_videos:
                            break

                # Save checkpoint after each page
                checkpoint.next_page_token = next_page_token
                checkpoint.last_run = datetime.now(timezone.utc).isoformat()
                save_checkpoint(checkpoint, self.checkpoint_path)

                if not next_page_token:
                    logger.info("All pages exhausted — crawl complete.")
                    break
                page_token = next_page_token

        # Final checkpoint with no pending token
        checkpoint.next_page_token = None
        checkpoint.last_run = datetime.now(timezone.utc).isoformat()
        save_checkpoint(checkpoint, self.checkpoint_path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_transcript_guarded(self, video_id: str) -> tuple[str, str, list[dict[str, Any]]]:
        """Fetch transcript with concurrency guard."""
        async with self.transcript_semaphore:
            return await _fetch_transcript(video_id)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    import argparse

    parser = argparse.ArgumentParser(description="Crawl John Savill YouTube channel")
    parser.add_argument("--max-videos", type=int, default=None, help="Limit number of videos")
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT_PATH))
    parser.add_argument("--output", default="youtube_videos.json", help="Output JSON file")
    args = parser.parse_args()

    crawler = YouTubeCrawler(
        checkpoint_path=Path(args.checkpoint),
        max_videos=args.max_videos,
    )
    videos = await crawler.crawl_all()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(videos, indent=2))
    logger.info("Wrote %d videos to %s", len(videos), output_path)


if __name__ == "__main__":
    asyncio.run(_main())
