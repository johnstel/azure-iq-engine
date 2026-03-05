"""
Tests for the SearchIndexer (src/ingestion/indexer.py).

All Azure AI Search HTTP calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ingestion.indexer import (
    IndexStats,
    SearchIndexer,
    SearchIndexerConfig,
    _batchify,
    _ensure_string_collection,
)


# ── _batchify ─────────────────────────────────────────────────────────────────

class TestBatchify:
    def test_single_batch(self):
        items = list(range(5))
        batches = _batchify(items, size=10)
        assert batches == [list(range(5))]

    def test_multiple_batches(self):
        items = list(range(25))
        batches = _batchify(items, size=10)
        assert len(batches) == 3
        assert batches[0] == list(range(10))
        assert batches[1] == list(range(10, 20))
        assert batches[2] == list(range(20, 25))

    def test_empty_list(self):
        assert _batchify([], size=10) == []

    def test_exact_boundary(self):
        items = list(range(10))
        batches = _batchify(items, size=10)
        assert len(batches) == 1


# ── _ensure_string_collection ─────────────────────────────────────────────────

class TestEnsureStringCollection:
    def test_none_returns_empty_list(self):
        assert _ensure_string_collection(None) == []

    def test_list_returned_as_is(self):
        assert _ensure_string_collection(["a", "b"]) == ["a", "b"]

    def test_bare_string_wrapped_in_list(self):
        assert _ensure_string_collection("fabric-iq") == ["fabric-iq"]

    def test_empty_list_returned_as_is(self):
        assert _ensure_string_collection([]) == []


# ── SearchIndexerConfig ───────────────────────────────────────────────────────

class TestSearchIndexerConfig:
    def test_docs_index_url_format(self):
        config = SearchIndexerConfig(
            search_endpoint="https://search.example.com",
            search_api_key="key",
            index_name="my-index",
            api_version="2024-07-01",
        )
        url = config.docs_index_url()
        assert "my-index" in url
        assert "2024-07-01" in url
        assert "docs/index" in url

    def test_docs_search_url_format(self):
        config = SearchIndexerConfig(
            search_endpoint="https://search.example.com",
            search_api_key="key",
            index_name="my-index",
            api_version="2024-07-01",
        )
        url = config.docs_search_url()
        assert "docs/search" in url


# ── SearchIndexer._apply_dedup ────────────────────────────────────────────────

def _make_indexer() -> SearchIndexer:
    config = SearchIndexerConfig(
        search_endpoint="https://search.example.com",
        search_api_key="fake-key",
    )
    return SearchIndexer(config=config)


class TestApplyDedup:
    def test_all_new_chunks_indexed(self):
        chunks = [
            {"chunk_id": "c1", "fingerprint": "fp1"},
            {"chunk_id": "c2", "fingerprint": "fp2"},
        ]
        indexer = _make_indexer()
        to_index, skipped = indexer._apply_dedup(chunks, existing={})
        assert len(to_index) == 2
        assert skipped == 0

    def test_unchanged_chunk_skipped(self):
        chunks = [{"chunk_id": "c1", "fingerprint": "fp1"}]
        existing = {"c1": "fp1"}  # same fingerprint
        indexer = _make_indexer()
        to_index, skipped = indexer._apply_dedup(chunks, existing=existing)
        assert len(to_index) == 0
        assert skipped == 1

    def test_changed_fingerprint_indexed(self):
        chunks = [{"chunk_id": "c1", "fingerprint": "fp-new"}]
        existing = {"c1": "fp-old"}  # different fingerprint
        indexer = _make_indexer()
        to_index, skipped = indexer._apply_dedup(chunks, existing=existing)
        assert len(to_index) == 1
        assert skipped == 0

    def test_mixed_chunks(self):
        chunks = [
            {"chunk_id": "c1", "fingerprint": "fp1"},  # unchanged
            {"chunk_id": "c2", "fingerprint": "fp2-new"},  # changed
            {"chunk_id": "c3", "fingerprint": "fp3"},  # new
        ]
        existing = {"c1": "fp1", "c2": "fp2-old"}
        indexer = _make_indexer()
        to_index, skipped = indexer._apply_dedup(chunks, existing=existing)
        assert skipped == 1
        assert len(to_index) == 2


# ── SearchIndexer.index_chunks (mocked HTTP) ──────────────────────────────────

@pytest.mark.asyncio
async def test_index_chunks_raises_when_not_configured():
    """index_chunks raises RuntimeError if SEARCH_ENDPOINT is missing."""
    config = SearchIndexerConfig(search_endpoint="", search_api_key="key")
    indexer = SearchIndexer(config=config)
    with pytest.raises(RuntimeError, match="SEARCH_ENDPOINT"):
        await indexer.index_chunks([{"chunk_id": "c1", "content": "Hello."}])


@pytest.mark.asyncio
async def test_index_chunks_raises_when_api_key_missing():
    config = SearchIndexerConfig(
        search_endpoint="https://search.example.com", search_api_key=None
    )
    indexer = SearchIndexer(config=config)
    with pytest.raises(RuntimeError, match="SEARCH_API_KEY"):
        await indexer.index_chunks([{"chunk_id": "c1", "content": "Hello."}])


@pytest.mark.asyncio
async def test_index_chunks_returns_stats_on_success():
    """Mock all HTTP calls; verify IndexStats are returned."""
    config = SearchIndexerConfig(
        search_endpoint="https://search.example.com",
        search_api_key="fake-key",
        index_name="test-index",
    )
    indexer = SearchIndexer(config=config)

    chunks = [
        {"chunk_id": "c1", "content": "Hello.", "fingerprint": "fp1", "iq_layers": []},
    ]

    # Mock fingerprint fetch: 404 (index empty)
    fetch_response = MagicMock()
    fetch_response.status_code = 404
    fetch_response.raise_for_status = MagicMock()
    fetch_response.json.return_value = {"value": []}

    # Mock upload response: all succeed
    upload_response = MagicMock()
    upload_response.status_code = 200
    upload_response.raise_for_status = MagicMock()
    upload_response.json.return_value = {
        "value": [{"key": "c1", "statusCode": 200, "succeeded": True}]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    # First call = fingerprint fetch (returns 404), second = upload
    mock_client.post = AsyncMock(side_effect=[fetch_response, upload_response])

    with patch("httpx.AsyncClient", return_value=mock_client):
        stats = await indexer.index_chunks(chunks)

    assert isinstance(stats, IndexStats)
    assert stats.total == 1
    assert stats.indexed == 1
    assert stats.failed == 0


@pytest.mark.asyncio
async def test_index_chunks_skips_unchanged_chunk():
    """When a chunk's fingerprint matches the index, it should be skipped."""
    config = SearchIndexerConfig(
        search_endpoint="https://search.example.com",
        search_api_key="fake-key",
    )
    indexer = SearchIndexer(config=config)

    chunks = [
        {"chunk_id": "c1", "content": "Hello.", "fingerprint": "fp1", "iq_layers": []},
    ]

    # Fingerprint fetch returns the same fingerprint — chunk is already indexed
    fetch_response = MagicMock()
    fetch_response.status_code = 200
    fetch_response.raise_for_status = MagicMock()
    fetch_response.json.return_value = {
        "value": [{"chunk_id": "c1", "fingerprint": "fp1"}]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=fetch_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        stats = await indexer.index_chunks(chunks)

    assert stats.skipped_dedup == 1
    assert stats.indexed == 0
