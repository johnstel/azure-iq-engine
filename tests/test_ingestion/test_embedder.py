"""
Tests for the EmbeddingPipeline (src/ingestion/embedder.py).

All Azure OpenAI calls are mocked — no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ingestion.embedder import EmbedderConfig, EmbeddingPipeline

# text-embedding-3-large produces 1536-dimensional vectors
_EMBEDDING_DIMENSIONS = 1536


def _make_chunk(idx: int = 0) -> dict:
    return {
        "chunk_id": f"chunk-{idx}",
        "source_url": "https://example.com/doc",
        "content": f"This is the content for chunk number {idx}.",
        "token_count": 10,
    }


# ── Graceful degradation (no API key) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_chunks_no_foundry_key_returns_chunks_without_embeddings():
    """When FOUNDRY_KEY is not set, chunks are returned unchanged (no embedding key added)."""
    config = EmbedderConfig(foundry_key=None)
    pipeline = EmbeddingPipeline(config=config)
    chunks = [_make_chunk(0), _make_chunk(1)]
    result = await pipeline.embed_chunks(chunks)
    assert len(result) == 2
    # No embedding should be added (API was skipped)
    for chunk in result:
        assert "embedding" not in chunk or chunk.get("embedding") is None


# ── EmbedderConfig ────────────────────────────────────────────────────────────

class TestEmbedderConfig:
    def test_embeddings_url_format(self):
        config = EmbedderConfig(
            foundry_base_url="https://my-foundry.azure.com",
            foundry_key="key",
            model_deployment="text-embedding-3-large",
            api_version="2024-06-01",
        )
        url = config.embeddings_url()
        assert "text-embedding-3-large" in url
        assert "embeddings" in url
        assert "2024-06-01" in url

    def test_trailing_slash_stripped(self):
        config = EmbedderConfig(foundry_base_url="https://my-foundry.azure.com/")
        url = config.embeddings_url()
        assert "//" not in url.replace("https://", "")

    def test_default_batch_size(self):
        config = EmbedderConfig()
        assert config.batch_size == 16

    def test_default_max_concurrent(self):
        config = EmbedderConfig()
        assert config.max_concurrent == 5


# ── Mocked embedding calls ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_chunks_attaches_embedding_to_each_chunk(tmp_path):
    """Mock the HTTP client to return fake embeddings; verify they are attached."""
    fake_embedding = [0.1] * _EMBEDDING_DIMENSIONS

    config = EmbedderConfig(
        foundry_base_url="https://fake.azure.com",
        foundry_key="fake-key",
        batch_size=16,
        checkpoint_dir=tmp_path,
    )
    pipeline = EmbeddingPipeline(config=config)

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "data": [{"embedding": fake_embedding, "index": 0}],
        "usage": {"total_tokens": 10},
    }

    chunks = [_make_chunk(0)]

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=fake_response)
        mock_client_class.return_value = mock_client

        result = await pipeline.embed_chunks(chunks, checkpoint_key="test")

    assert result[0].get("embedding") is not None
    assert len(result[0]["embedding"]) == _EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_embed_empty_chunks_list_returns_empty(tmp_path):
    config = EmbedderConfig(foundry_key="fake-key", checkpoint_dir=tmp_path)
    pipeline = EmbeddingPipeline(config=config)
    result = await pipeline.embed_chunks([])
    assert result == []
