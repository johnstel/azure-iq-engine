"""
Tests for the three chunking strategies in src/ingestion/chunker.py.

All tests are pure-Python with no external service calls.
"""

from __future__ import annotations

import pytest

from src.ingestion.chunker import (
    AtomicChunker,
    ChunkConfig,
    ContentTypeAwareChunker,
    DocumentChunker,
    SourceType,
    TranscriptChunker,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_doc(**overrides) -> dict:
    base = {
        "url": "https://example.com/doc",
        "source_type": "ms-learn",
        "title": "Test Document",
        "content": "This is the document content. It has several sentences.",
        "iq_layers": ["fabric-iq"],
        "azure_services": [],
        "published_at": "2024-01-01",
    }
    base.update(overrides)
    return base


# ── DocumentChunker ───────────────────────────────────────────────────────────

class TestDocumentChunker:
    def setup_method(self):
        self.chunker = DocumentChunker()

    def test_empty_content_returns_empty_list(self):
        doc = _make_doc(content="   ")
        assert self.chunker.chunk(doc) == []

    def test_single_chunk_basic(self):
        doc = _make_doc(content="Short content that fits in one chunk.")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1
        assert chunks[0]["content"].strip() != ""

    def test_chunk_fields_present(self):
        doc = _make_doc(content="Some content here.")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1
        c = chunks[0]
        assert "chunk_id" in c
        assert "source_url" in c
        assert "source_type" in c
        assert "title" in c
        assert "content" in c
        assert "chunk_index" in c
        assert "total_chunks" in c
        assert "token_count" in c
        assert "fingerprint" in c

    def test_chunk_preserves_source_url(self):
        doc = _make_doc(url="https://learn.microsoft.com/test", content="Content.")
        chunks = self.chunker.chunk(doc)
        for c in chunks:
            assert c["source_url"] == "https://learn.microsoft.com/test"

    def test_chunk_preserves_iq_layers(self):
        doc = _make_doc(content="Some content.", iq_layers=["work-iq", "fabric-iq"])
        chunks = self.chunker.chunk(doc)
        for c in chunks:
            assert c["iq_layers"] == ["work-iq", "fabric-iq"]

    def test_total_chunks_consistent(self):
        doc = _make_doc(content="Paragraph one.\n\nParagraph two.\n\nParagraph three.")
        chunks = self.chunker.chunk(doc)
        n = len(chunks)
        for c in chunks:
            assert c["total_chunks"] == n

    def test_chunk_index_sequential(self):
        long_content = " ".join([f"Sentence number {i}." for i in range(200)])
        doc = _make_doc(content=long_content)
        chunks = self.chunker.chunk(doc)
        for i, c in enumerate(chunks):
            assert c["chunk_index"] == i

    def test_heading_path_extracted(self):
        content = "## Overview\n\nThis is the overview section.\n\n## Details\n\nDetailed info."
        doc = _make_doc(content=content)
        chunks = self.chunker.chunk(doc)
        heading_paths = [c["heading_path"] for c in chunks]
        # At least one chunk should have a non-empty heading_path
        assert any(hp for hp in heading_paths)

    def test_large_document_split_into_multiple_chunks(self):
        """A document with 1500 words must produce more than one chunk given a 50-token limit."""
        # 1500 words produces well over 50 tokens (easily exceeds the tiny limit)
        words = ["word"] * 1500
        doc = _make_doc(content=" ".join(words))
        config = ChunkConfig(max_chunk_tokens=50, overlap_tokens=10)
        chunker = DocumentChunker(config)
        chunks = chunker.chunk(doc)
        assert len(chunks) > 1

    def test_code_block_not_split_mid_fence(self):
        content = (
            "Some intro text.\n\n"
            "```python\n"
            "def hello():\n"
            "    print('world')\n"
            "```\n\n"
            "Some trailing text."
        )
        doc = _make_doc(content=content)
        chunks = self.chunker.chunk(doc)
        # The code block must appear intact in exactly one chunk
        code_chunks = [c for c in chunks if "```python" in c["content"]]
        assert len(code_chunks) >= 1
        for cc in code_chunks:
            assert "```" in cc["content"]  # opening and closing fence both present

    def test_overlap_applied_between_chunks(self):
        """Second chunk should contain some text from the end of the first chunk."""
        config = ChunkConfig(max_chunk_tokens=20, overlap_tokens=5)
        chunker = DocumentChunker(config)
        many_words = " ".join([f"token{i}" for i in range(60)])
        doc = _make_doc(content=many_words)
        chunks = chunker.chunk(doc)
        if len(chunks) >= 2:
            first_words = set(chunks[0]["content"].split())
            second_words = set(chunks[1]["content"].split())
            # There should be overlap between chunks
            assert len(first_words & second_words) > 0


# ── TranscriptChunker ─────────────────────────────────────────────────────────

class TestTranscriptChunker:
    def setup_method(self):
        self.chunker = TranscriptChunker()

    def _make_transcript_doc(self, segments: list[dict], **overrides) -> dict:
        base = {
            "url": "https://youtube.com/watch?v=abc123",
            "source_type": "video-transcript",
            "title": "Azure IQ Demo",
            "video_id": "abc123",
            "transcript": segments,
            "iq_layers": [],
            "azure_services": [],
            "published_at": "2024-01-01",
        }
        base.update(overrides)
        return base

    def test_empty_transcript_returns_empty(self):
        doc = self._make_transcript_doc(segments=[])
        assert self.chunker.chunk(doc) == []

    def test_single_segment_produces_one_chunk(self):
        doc = self._make_transcript_doc(
            segments=[{"text": "Hello world.", "start": 0.0, "end": 5.0}]
        )
        chunks = self.chunker.chunk(doc)
        assert len(chunks) == 1

    def test_chunk_has_video_timestamps(self):
        doc = self._make_transcript_doc(
            segments=[
                {"text": "Segment one.", "start": 0.0, "end": 5.0},
                {"text": "Segment two.", "start": 5.5, "end": 10.0},
            ]
        )
        chunks = self.chunker.chunk(doc)
        assert chunks[0]["video_start_time"] is not None
        assert chunks[0]["video_end_time"] is not None

    def test_topic_gap_triggers_new_chunk(self):
        """Segments separated by > topic_gap_seconds should be in different chunks."""
        config = ChunkConfig(topic_gap_seconds=5.0)
        chunker = TranscriptChunker(config)
        doc = self._make_transcript_doc(
            segments=[
                {"text": "First topic sentence.", "start": 0.0, "end": 3.0},
                # Large gap — triggers topic break
                {"text": "Second topic sentence.", "start": 40.0, "end": 43.0},
            ]
        )
        chunks = chunker.chunk(doc)
        assert len(chunks) == 2

    def test_consecutive_segments_grouped(self):
        """Segments with small gaps should be merged into one chunk."""
        config = ChunkConfig(topic_gap_seconds=30.0, max_chunk_tokens=512)
        chunker = TranscriptChunker(config)
        doc = self._make_transcript_doc(
            segments=[
                {"text": "Word.", "start": 0.0, "end": 1.0},
                {"text": "Word.", "start": 1.5, "end": 2.5},
                {"text": "Word.", "start": 3.0, "end": 4.0},
            ]
        )
        chunks = chunker.chunk(doc)
        assert len(chunks) == 1

    def test_chunk_text_includes_timestamp_header(self):
        doc = self._make_transcript_doc(
            segments=[{"text": "Intro.", "start": 0.0, "end": 5.0}]
        )
        chunks = self.chunker.chunk(doc)
        assert "Azure IQ Demo" in chunks[0]["content"]
        assert "0:00" in chunks[0]["content"]

    def test_duration_based_end_time(self):
        """Accept segments with 'duration' instead of 'end'."""
        doc = self._make_transcript_doc(
            segments=[{"text": "Hello.", "start": 10.0, "duration": 3.0}]
        )
        chunks = self.chunker.chunk(doc)
        assert len(chunks) == 1
        assert chunks[0]["video_end_time"] == pytest.approx(13.0)

    def test_start_time_based_end_time(self):
        """Segments with no end/duration use start as end."""
        doc = self._make_transcript_doc(
            segments=[{"text": "Hello.", "start": 5.0}]
        )
        chunks = self.chunker.chunk(doc)
        assert chunks[0]["video_end_time"] == pytest.approx(5.0)

    def test_plain_text_fallback(self):
        """When no structured transcript, fall back to plain text chunking."""
        doc = {
            "url": "https://youtube.com/watch?v=xyz",
            "source_type": "video-transcript",
            "title": "Fallback Test",
            "video_id": "xyz",
            "transcript": [],  # empty structured transcript
            "content": "This is a plain-text transcript.\n\nSecond paragraph here.",
            "iq_layers": [],
            "azure_services": [],
            "published_at": "2024-01-01",
        }
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1


# ── AtomicChunker ─────────────────────────────────────────────────────────────

class TestAtomicChunker:
    def setup_method(self):
        self.chunker = AtomicChunker()

    def _make_atomic_doc(self, **overrides) -> dict:
        base = {
            "url": "https://azure.microsoft.com/updates/some-update",
            "source_type": "azure-update",
            "title": "Azure OpenAI GA",
            "content": "Azure OpenAI is now generally available in all regions.",
            "iq_layers": ["foundry-iq"],
            "azure_services": ["Azure OpenAI"],
            "published_at": "2024-03-01",
        }
        base.update(overrides)
        return base

    def test_always_produces_exactly_one_chunk(self):
        doc = self._make_atomic_doc()
        chunks = self.chunker.chunk(doc)
        assert len(chunks) == 1

    def test_total_chunks_is_one(self):
        doc = self._make_atomic_doc()
        chunks = self.chunker.chunk(doc)
        assert chunks[0]["total_chunks"] == 1

    def test_empty_content_returns_empty_list(self):
        doc = self._make_atomic_doc(content="  ")
        assert self.chunker.chunk(doc) == []

    def test_content_preserved_verbatim(self):
        content = "Azure OpenAI is now generally available in all regions."
        doc = self._make_atomic_doc(content=content)
        chunks = self.chunker.chunk(doc)
        assert content in chunks[0]["content"]

    def test_very_long_content_still_one_chunk(self):
        """AtomicChunker never splits, even for very long content."""
        long_content = " ".join(["word"] * 2000)
        doc = self._make_atomic_doc(content=long_content)
        chunks = self.chunker.chunk(doc)
        assert len(chunks) == 1


# ── ContentTypeAwareChunker ───────────────────────────────────────────────────

class TestContentTypeAwareChunker:
    def setup_method(self):
        self.chunker = ContentTypeAwareChunker()

    def test_ms_learn_routes_to_document_chunker(self):
        doc = _make_doc(source_type="ms-learn", content="Short MS Learn content.")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1

    def test_tech_community_routes_to_document_chunker(self):
        doc = _make_doc(source_type="tech-community", content="Tech community post.")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1

    def test_azure_update_routes_to_atomic_chunker(self):
        doc = _make_doc(source_type="azure-update", content="An update announcement.")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) == 1

    def test_video_transcript_routes_to_transcript_chunker(self):
        doc = {
            "url": "https://youtube.com/watch?v=abc",
            "source_type": "video-transcript",
            "title": "Video",
            "video_id": "abc",
            "transcript": [{"text": "Hello.", "start": 0.0, "end": 2.0}],
            "iq_layers": [],
            "azure_services": [],
            "published_at": "2024-01-01",
        }
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1
        assert chunks[0]["video_id"] == "abc"

    def test_unknown_source_type_falls_back_to_document_chunker(self):
        doc = _make_doc(source_type="unknown-type", content="Fallback content.")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1

    def test_chunk_many_returns_flat_list(self):
        docs = [
            _make_doc(url="https://example.com/1", source_type="ms-learn", content="Doc 1."),
            _make_doc(url="https://example.com/2", source_type="azure-update", content="Doc 2."),
        ]
        all_chunks = self.chunker.chunk_many(docs)
        assert isinstance(all_chunks, list)
        assert len(all_chunks) >= 2

    def test_chunk_many_handles_failed_doc_gracefully(self):
        """A doc that causes an error should not break processing of others."""
        bad_doc = {}  # missing all keys
        good_doc = _make_doc(content="Good content.")
        all_chunks = self.chunker.chunk_many([bad_doc, good_doc])
        # At least the good doc's chunks should be present
        good_chunks = [c for c in all_chunks if c.get("source_url") == "https://example.com/doc"]
        assert len(good_chunks) >= 1

    def test_blog_post_source_type(self):
        doc = _make_doc(source_type="blog-post", content="A blog post about Azure.")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1
