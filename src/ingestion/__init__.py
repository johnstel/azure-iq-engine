# Ingestion pipeline
#
# NOTE: embedder.py and indexer.py are not yet implemented.
# Their imports are guarded so the package loads cleanly during development.
# Remove the try/except guards once those modules land.

from .chunker import ChunkConfig, SourceType, ContentTypeAwareChunker
from .fingerprint import ChunkFingerprint, compute_fingerprint, should_index

# EmbeddingPipeline — guarded until src/ingestion/embedder.py is implemented
try:
    from .embedder import EmbeddingPipeline, EmbedderConfig  # type: ignore[import]
except ImportError:
    EmbeddingPipeline = None   # type: ignore[assignment,misc]
    EmbedderConfig = None      # type: ignore[assignment,misc]

# SearchIndexer — guarded until src/ingestion/indexer.py is implemented
try:
    from .indexer import SearchIndexer, SearchIndexerConfig, IndexStats  # type: ignore[import]
except ImportError:
    SearchIndexer = None       # type: ignore[assignment,misc]
    SearchIndexerConfig = None  # type: ignore[assignment,misc]
    IndexStats = None          # type: ignore[assignment,misc]

__all__ = [
    # Chunker
    "ContentTypeAwareChunker",
    "SourceType",
    "ChunkConfig",
    # Embedder (may be None until embedder.py is implemented)
    "EmbeddingPipeline",
    "EmbedderConfig",
    # Fingerprint
    "ChunkFingerprint",
    "compute_fingerprint",
    "should_index",
    # Indexer (may be None until indexer.py is implemented)
    "SearchIndexer",
    "SearchIndexerConfig",
    "IndexStats",
]
