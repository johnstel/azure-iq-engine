"""
Ingestion crawlers for Azure IQ Engine.

Each crawler fetches, parses, and normalises content from a specific source
into the common document schema consumed by the chunker and indexer pipeline.

Available crawlers
------------------
MSLearnCrawler          — Microsoft Learn documentation
YouTubeCrawler          — John Savill's Technical Training (YouTube)
AzureUpdatesCrawler     — Azure Updates RSS feed (atomic posts)
TechCommunityCrawler    — Microsoft Tech Community blogs (AI / Fabric / Dev)
"""

# Microsoft Learn (forward-declared — implementation pending)
try:
    from .mslearn_crawler import MSLearnCrawler, CrawlerConfig, CrawledDocument
except ImportError:
    MSLearnCrawler = None  # type: ignore[assignment,misc]
    CrawlerConfig = None   # type: ignore[assignment,misc]
    CrawledDocument = None  # type: ignore[assignment,misc]

# YouTube — John Savill's Technical Training
from .youtube_crawler import (
    YouTubeCrawler,
    VideoMetadata,
    CrawlerCheckpoint as YouTubeCrawlerCheckpoint,
    detect_iq_layers as youtube_detect_iq_layers,
    detect_azure_services as youtube_detect_azure_services,
    compute_fingerprint as youtube_compute_fingerprint,
)

# Azure Updates RSS feed
from .azure_updates_crawler import (
    AzureUpdatesCrawler,
    AzureUpdate,
    UpdatesCheckpoint,
    detect_iq_layers as updates_detect_iq_layers,
    detect_azure_services as updates_detect_azure_services,
    compute_fingerprint as updates_compute_fingerprint,
)

# Microsoft Tech Community blogs
from .techcommunity_crawler import (
    TechCommunityCrawler,
    TechCommunityPost,
    TechCommunityCheckpoint,
    detect_iq_layers as tc_detect_iq_layers,
    detect_azure_services as tc_detect_azure_services,
    compute_fingerprint as tc_compute_fingerprint,
)

__all__ = [
    # MS Learn (may be None if not yet implemented)
    "MSLearnCrawler",
    "CrawlerConfig",
    "CrawledDocument",
    # YouTube
    "YouTubeCrawler",
    "VideoMetadata",
    "YouTubeCrawlerCheckpoint",
    # Azure Updates
    "AzureUpdatesCrawler",
    "AzureUpdate",
    "UpdatesCheckpoint",
    # Tech Community
    "TechCommunityCrawler",
    "TechCommunityPost",
    "TechCommunityCheckpoint",
]
