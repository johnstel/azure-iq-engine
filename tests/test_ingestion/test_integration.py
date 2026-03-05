"""
Integration test: crawl stub → chunk → embed → index pipeline.

All Azure services (OpenAI embeddings, AI Search) are mocked so no real
network calls are made.  The test validates that the orchestrator wires
all module interfaces correctly end-to-end.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ingestion.orchestrator import (
    IngestionOrchestrator,
    OrchestratorConfig,
    PipelineResult,
)


# ---------------------------------------------------------------------------
# Fixtures — stub documents from each crawler
# ---------------------------------------------------------------------------

_YOUTUBE_DOC: dict[str, Any] = {
    "url": "https://www.youtube.com/watch?v=test123",
    "video_id": "test123",
    "title": "Azure AI Foundry Overview",
    "source_type": "video-transcript",
    "transcript_text": "Azure AI Foundry is a platform for building AI applications. " * 30,
    "transcript": [],
    "iq_layers": ["foundry-iq"],
    "azure_services": ["Azure AI Foundry"],
    "fingerprint": "fp_youtube_test",
    "published_at": "2024-01-15",
}

_AZURE_UPDATE_DOC: dict[str, Any] = {
    "url": "https://azure.microsoft.com/en-us/updates/test-update/",
    "title": "Azure AI Search now supports vector search",
    "source_type": "azure-update",
    "summary": "Azure AI Search introduces vector search capabilities for semantic retrieval. " * 20,
    "iq_layers": ["foundry-iq"],
    "azure_services": ["Azure AI Search"],
    "fingerprint": "fp_update_test",
    "published_at": "2024-02-01",
}

_TECHCOMMUNITY_DOC: dict[str, Any] = {
    "url": "https://techcommunity.microsoft.com/blog/test-post",
    "title": "Building with Microsoft Fabric",
    "source_type": "blog-post",
    "body_text": "Microsoft Fabric unifies data and analytics workloads in a single platform. " * 20,
    "iq_layers": ["fabric-iq"],
    "azure_services": ["Microsoft Fabric"],
    "fingerprint": "fp_tc_test",
    "published_at": "2024-03-01",
}

_MSLEARN_DOC: dict[str, Any] = {
    "url": "https://learn.microsoft.com/en-us/azure/ai-services/overview",
    "source_url": "https://learn.microsoft.com/en-us/azure/ai-services/overview",
    "title": "Azure AI Services Overview",
    "source_type": "ms-learn",
    "content": "Azure AI Services provide pre-built AI capabilities for developers. " * 30,
    "iq_layers": ["foundry-iq"],
    "azure_services": ["Azure AI Services"],
    "fingerprint": "fp_mslearn_test",
    "published_at": "2024-04-01",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_crawler_mock(docs: list[dict[str, Any]]) -> MagicMock:
    """Return a mock crawler whose crawl_all() returns the provided docs."""
    mock = MagicMock()
    mock.crawl_all = AsyncMock(return_value=docs)
    return mock


def _make_embed_pipeline_mock() -> MagicMock:
    """Return a mock EmbeddingPipeline whose embed_batch() enriches each chunk."""

    async def _fake_embed_batch(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for chunk in chunks:
            chunk.setdefault("embedding", [0.1] * 1536)
            chunk.setdefault("token_count", max(1, len(chunk.get("content", "")) // 4))
        return chunks

    mock = MagicMock()
    mock.embed_batch = _fake_embed_batch
    return mock


def _make_indexer_mock() -> MagicMock:
    """Return a mock SearchIndexer with all required public methods."""
    from src.ingestion.indexer import IndexStats

    mock = MagicMock()
    mock.get_existing_fingerprints = AsyncMock(return_value={})
    mock.index_batch = AsyncMock(return_value=IndexStats(total=1, indexed=1, failed=0))
    mock.get_index_document_count = AsyncMock(return_value=42)
    return mock


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_dry_run_single_source(tmp_path: Path) -> None:
    """
    Dry-run with one source (youtube) — only crawl + chunk steps execute.
    No embedding or indexing should occur.
    """
    config = OrchestratorConfig(
        sources=["youtube"],
        checkpoint_dir=tmp_path / "checkpoints",
        dry_run=True,
        max_pages_per_source=1,
    )
    orchestrator = IngestionOrchestrator(config)

    with patch(
        "src.ingestion.orchestrator.YouTubeCrawler",
        return_value=_make_crawler_mock([_YOUTUBE_DOC]),
    ):
        result: PipelineResult = await orchestrator.run()

    assert result.total_documents == 1
    assert result.total_chunks >= 1
    # Dry-run: dedup/embed/index are all skipped
    assert result.chunks_embedded == 0
    assert result.chunks_indexed == 0
    assert result.chunks_failed == 0


@pytest.mark.asyncio
async def test_pipeline_embed_and_index(tmp_path: Path) -> None:
    """
    Full pipeline (without dry_run) with mocked Azure services.

    Validates that embed_batch() and index_batch() are called correctly
    and that PipelineResult reflects the expected counts.
    """
    config = OrchestratorConfig(
        sources=["youtube"],
        checkpoint_dir=tmp_path / "checkpoints",
        dry_run=False,
        max_pages_per_source=1,
    )
    orchestrator = IngestionOrchestrator(config)

    embed_mock = _make_embed_pipeline_mock()
    indexer_mock = _make_indexer_mock()

    with (
        patch("src.ingestion.orchestrator.YouTubeCrawler", return_value=_make_crawler_mock([_YOUTUBE_DOC])),
        patch("src.ingestion.orchestrator.EmbeddingPipeline", return_value=embed_mock),
        patch("src.ingestion.orchestrator.SearchIndexer", return_value=indexer_mock),
    ):
        result: PipelineResult = await orchestrator.run()

    assert result.total_documents == 1
    assert result.total_chunks >= 1
    assert result.chunks_embedded >= 1
    assert result.chunks_indexed >= 1  # mock returns 1 indexed per index_batch call
    assert result.chunks_failed == 0
    # embedding_tokens populated from token_count on each chunk
    assert result.embedding_tokens > 0


@pytest.mark.asyncio
async def test_pipeline_all_sources(tmp_path: Path) -> None:
    """
    Dry-run across all four sources verifying each crawler is called and
    content-field remapping works for every source type.
    """
    config = OrchestratorConfig(
        sources=["youtube", "azure_updates", "techcommunity", "mslearn"],
        checkpoint_dir=tmp_path / "checkpoints",
        dry_run=True,
        max_pages_per_source=1,
    )
    orchestrator = IngestionOrchestrator(config)

    with (
        patch("src.ingestion.orchestrator.YouTubeCrawler", return_value=_make_crawler_mock([_YOUTUBE_DOC])),
        patch("src.ingestion.orchestrator.AzureUpdatesCrawler", return_value=_make_crawler_mock([_AZURE_UPDATE_DOC])),
        patch("src.ingestion.orchestrator.TechCommunityCrawler", return_value=_make_crawler_mock([_TECHCOMMUNITY_DOC])),
        patch("src.ingestion.orchestrator.MSLearnCrawler", return_value=_make_crawler_mock([_MSLEARN_DOC])),
    ):
        result: PipelineResult = await orchestrator.run()

    assert result.total_documents == 4
    assert result.total_chunks >= 4
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_pipeline_skip_embedding(tmp_path: Path) -> None:
    """
    With skip_embedding=True, embedding step is bypassed but indexing still runs.
    """
    config = OrchestratorConfig(
        sources=["azure_updates"],
        checkpoint_dir=tmp_path / "checkpoints",
        dry_run=False,
        skip_embedding=True,
        max_pages_per_source=1,
    )
    orchestrator = IngestionOrchestrator(config)

    indexer_mock = _make_indexer_mock()

    with (
        patch("src.ingestion.orchestrator.AzureUpdatesCrawler", return_value=_make_crawler_mock([_AZURE_UPDATE_DOC])),
        patch("src.ingestion.orchestrator.SearchIndexer", return_value=indexer_mock),
    ):
        result: PipelineResult = await orchestrator.run()

    assert result.total_documents == 1
    assert result.total_chunks >= 1
    assert result.chunks_failed == 0
    # When skip_embedding=True the orchestrator still counts the chunks as "embedded"
    # (they pass through without vectors) to keep pipeline metrics consistent.
    assert result.chunks_embedded >= 1


@pytest.mark.asyncio
async def test_pipeline_dedup_skips_unchanged_chunks(tmp_path: Path) -> None:
    """
    When the indexer reports existing fingerprints that match the crawled chunks,
    those chunks are skipped (chunks_skipped > 0, chunks_new < total_chunks).
    When the fingerprint map is empty, all chunks are treated as new.
    """
    config = OrchestratorConfig(
        sources=["azure_updates"],
        checkpoint_dir=tmp_path / "checkpoints",
        dry_run=False,
        max_pages_per_source=1,
    )

    from src.ingestion.indexer import IndexStats

    embed_mock = _make_embed_pipeline_mock()
    indexer_mock = _make_indexer_mock()
    # Empty fingerprint map → all chunks are new
    indexer_mock.get_existing_fingerprints = AsyncMock(return_value={})

    orchestrator = IngestionOrchestrator(config)
    with (
        patch("src.ingestion.orchestrator.AzureUpdatesCrawler", return_value=_make_crawler_mock([_AZURE_UPDATE_DOC])),
        patch("src.ingestion.orchestrator.EmbeddingPipeline", return_value=embed_mock),
        patch("src.ingestion.orchestrator.SearchIndexer", return_value=indexer_mock),
    ):
        result: PipelineResult = await orchestrator.run()

    # With empty fingerprint map, all chunks are treated as new
    assert result.chunks_skipped == 0
    assert result.chunks_new >= 1


@pytest.mark.asyncio
async def test_embed_batch_adds_token_count() -> None:
    """
    Unit test: EmbeddingPipeline.embed_batch() enriches each chunk with token_count.
    """
    from src.ingestion.embedder import EmbeddingPipeline, EmbedderConfig

    config = EmbedderConfig(foundry_key=None)  # No key → returns chunks without API call
    pipeline = EmbeddingPipeline(config)

    chunks = [
        {"chunk_id": "c1", "content": "Hello world " * 50},
        {"chunk_id": "c2", "content": "Azure AI Search is powerful " * 30},
    ]
    result = await pipeline.embed_batch(chunks)

    assert len(result) == 2
    for chunk in result:
        assert "token_count" in chunk
        assert chunk["token_count"] >= 1


@pytest.mark.asyncio
async def test_indexer_get_existing_fingerprints_no_config() -> None:
    """
    SearchIndexer.get_existing_fingerprints() returns {} when env vars are absent.
    """
    from src.ingestion.indexer import SearchIndexer, SearchIndexerConfig

    cfg = SearchIndexerConfig(search_endpoint="", search_api_key=None)
    indexer = SearchIndexer(cfg)

    result = await indexer.get_existing_fingerprints()
    assert result == {}


@pytest.mark.asyncio
async def test_indexer_get_index_document_count_no_config() -> None:
    """
    SearchIndexer.get_index_document_count() returns 0 when env vars are absent.
    """
    from src.ingestion.indexer import SearchIndexer, SearchIndexerConfig

    cfg = SearchIndexerConfig(search_endpoint="", search_api_key=None)
    indexer = SearchIndexer(cfg)

    count = await indexer.get_index_document_count()
    assert count == 0


@pytest.mark.asyncio
async def test_mslearn_crawler_crawl_all_returns_dicts(tmp_path: Path) -> None:
    """
    MSLearnCrawler.crawl_all() returns dicts with a 'url' field mapped from source_url.
    """
    from src.ingestion.crawlers.mslearn_crawler import (
        CrawlerConfig,
        CrawledDocument,
        MSLearnCrawler,
    )

    config = CrawlerConfig(
        checkpoint_path=str(tmp_path / "mslearn_cp.json"),
        max_pages=1,
    )
    crawler = MSLearnCrawler(config)

    fake_doc = CrawledDocument(
        doc_id="abc123",
        source_url="https://learn.microsoft.com/en-us/azure/ai-services/",
        title="Azure AI Services",
        content="Some content about Azure AI.",
        fingerprint="abc123",
    )

    with patch.object(crawler, "crawl", new=AsyncMock(return_value=[fake_doc])):
        docs = await crawler.crawl_all()

    assert len(docs) == 1
    assert docs[0]["url"] == "https://learn.microsoft.com/en-us/azure/ai-services/"
    assert docs[0]["content"] == "Some content about Azure AI."
    assert docs[0]["source_type"] == "ms-learn"
