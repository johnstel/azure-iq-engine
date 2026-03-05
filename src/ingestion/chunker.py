"""
Content-Type-Aware Chunker (ADR-003).

Different content types require different chunking strategies.
Universal 512/128 chunking is replaced with per-source-type strategies.
"""

from dataclasses import dataclass
from enum import Enum


class ContentType(Enum):
    MS_LEARN = "ms-learn"
    VIDEO_TRANSCRIPT = "video-transcript"
    AZURE_UPDATE = "azure-update"
    BLOG_POST = "blog-post"
    ARCHITECTURE_PATTERN = "architecture"
    CODE_SAMPLE = "code-sample"


@dataclass
class ChunkConfig:
    """Chunking configuration per content type."""
    max_tokens: int
    overlap_tokens: int
    strategy: str  # "semantic", "sentence", "atomic", "narrative", "code"


# ADR-003: Content-type-aware chunking strategies
CHUNKING_STRATEGIES: dict[ContentType, ChunkConfig] = {
    ContentType.MS_LEARN: ChunkConfig(
        max_tokens=1000, overlap_tokens=128, strategy="semantic"
    ),
    ContentType.VIDEO_TRANSCRIPT: ChunkConfig(
        max_tokens=320, overlap_tokens=64, strategy="sentence"
    ),
    ContentType.AZURE_UPDATE: ChunkConfig(
        max_tokens=9999, overlap_tokens=0, strategy="atomic"  # No chunking
    ),
    ContentType.BLOG_POST: ChunkConfig(
        max_tokens=800, overlap_tokens=128, strategy="semantic"
    ),
    ContentType.ARCHITECTURE_PATTERN: ChunkConfig(
        max_tokens=1200, overlap_tokens=200, strategy="narrative"
    ),
    ContentType.CODE_SAMPLE: ChunkConfig(
        max_tokens=2000, overlap_tokens=0, strategy="code"
    ),
}


class ContentTypeAwareChunker:
    """
    Chunks content using the strategy appropriate for its content type.
    
    Phase 2 addition: parent-child chunking for improved retrieval quality.
    """

    def chunk(self, content: str, content_type: ContentType) -> list[dict]:
        """Split content into chunks using the appropriate strategy."""
        config = CHUNKING_STRATEGIES[content_type]

        if config.strategy == "atomic":
            return self._chunk_atomic(content)
        elif config.strategy == "sentence":
            return self._chunk_by_sentence(content, config)
        elif config.strategy == "semantic":
            return self._chunk_by_section(content, config)
        elif config.strategy == "narrative":
            return self._chunk_narrative(content, config)
        elif config.strategy == "code":
            return self._chunk_code(content, config)
        else:
            raise ValueError(f"Unknown strategy: {config.strategy}")

    def _chunk_atomic(self, content: str) -> list[dict]:
        """Treat entire content as a single chunk (Azure Updates)."""
        return [{"content": content.strip(), "chunk_index": 0}]

    def _chunk_by_sentence(self, content: str, config: ChunkConfig) -> list[dict]:
        """Split on sentence boundaries (video transcripts)."""
        # TODO: Implement sentence-boundary splitting with overlap
        raise NotImplementedError

    def _chunk_by_section(self, content: str, config: ChunkConfig) -> list[dict]:
        """Split on document section boundaries (MS Learn, blogs)."""
        # TODO: Implement section-aware splitting preserving tables/code blocks
        raise NotImplementedError

    def _chunk_narrative(self, content: str, config: ChunkConfig) -> list[dict]:
        """Larger chunks preserving narrative arc (architecture patterns)."""
        # TODO: Implement narrative chunking
        raise NotImplementedError

    def _chunk_code(self, content: str, config: ChunkConfig) -> list[dict]:
        """Split on function/class boundaries, never split a code block."""
        # TODO: Implement code-aware splitting
        raise NotImplementedError
