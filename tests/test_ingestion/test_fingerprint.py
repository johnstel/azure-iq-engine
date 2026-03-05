"""
Tests for SHA256 fingerprinting and deduplication (src/ingestion/fingerprint.py).
"""

from __future__ import annotations

import hashlib

import pytest

from src.ingestion.fingerprint import ChunkFingerprint, compute_fingerprint, should_index


# ── compute_fingerprint ───────────────────────────────────────────────────────

class TestComputeFingerprint:
    def test_returns_hex_string(self):
        fp = compute_fingerprint("https://example.com", "content")
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA256 hex digest is 64 chars

    def test_deterministic(self):
        fp1 = compute_fingerprint("https://example.com", "content")
        fp2 = compute_fingerprint("https://example.com", "content")
        assert fp1 == fp2

    def test_different_url_different_fingerprint(self):
        fp1 = compute_fingerprint("https://example.com/a", "content")
        fp2 = compute_fingerprint("https://example.com/b", "content")
        assert fp1 != fp2

    def test_different_content_different_fingerprint(self):
        fp1 = compute_fingerprint("https://example.com", "content A")
        fp2 = compute_fingerprint("https://example.com", "content B")
        assert fp1 != fp2

    def test_empty_content(self):
        fp = compute_fingerprint("https://example.com", "")
        assert len(fp) == 64

    def test_unicode_content(self):
        fp = compute_fingerprint("https://example.com", "日本語コンテンツ")
        assert len(fp) == 64

    def test_matches_manual_sha256(self):
        url = "https://example.com"
        content = "hello world"
        expected = hashlib.sha256(f"{url}:{content}".encode("utf-8")).hexdigest()
        assert compute_fingerprint(url, content) == expected


# ── should_index ──────────────────────────────────────────────────────────────

class TestShouldIndex:
    @pytest.mark.asyncio
    async def test_new_fingerprint_should_index(self):
        result = await should_index("abc123", existing_fingerprints={})
        assert result is True

    @pytest.mark.asyncio
    async def test_existing_same_fingerprint_skip(self):
        from datetime import datetime

        fp = compute_fingerprint("https://example.com", "content")
        existing = {
            fp: ChunkFingerprint(
                chunk_id="chunk-1",
                fingerprint=fp,
                source_url="https://example.com",
                source_type="ms-learn",
                indexed_at=datetime(2024, 1, 1),
            )
        }
        result = await should_index(fp, existing_fingerprints=existing)
        assert result is False

    @pytest.mark.asyncio
    async def test_changed_content_should_index(self):
        """A fingerprint that differs from existing is treated as changed content."""
        from datetime import datetime

        old_fp = compute_fingerprint("https://example.com", "old content")
        new_fp = compute_fingerprint("https://example.com", "new content")

        existing = {
            old_fp: ChunkFingerprint(
                chunk_id="chunk-1",
                fingerprint=old_fp,
                source_url="https://example.com",
                source_type="ms-learn",
                indexed_at=datetime(2024, 1, 1),
            )
        }
        # New fingerprint is not in existing — should be indexed
        result = await should_index(new_fp, existing_fingerprints=existing)
        assert result is True


# ── ChunkFingerprint dataclass ────────────────────────────────────────────────

class TestChunkFingerprint:
    def test_fields(self):
        from datetime import datetime

        fp = ChunkFingerprint(
            chunk_id="chunk-abc",
            fingerprint="deadbeef",
            source_url="https://example.com",
            source_type="ms-learn",
            indexed_at=datetime(2024, 6, 1),
            content_version=2,
        )
        assert fp.chunk_id == "chunk-abc"
        assert fp.fingerprint == "deadbeef"
        assert fp.content_version == 2

    def test_default_content_version(self):
        from datetime import datetime

        fp = ChunkFingerprint(
            chunk_id="chunk-1",
            fingerprint="abc",
            source_url="https://x.com",
            source_type="ms-learn",
            indexed_at=datetime(2024, 1, 1),
        )
        assert fp.content_version == 1
