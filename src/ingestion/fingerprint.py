"""
Content fingerprinting and deduplication (ADR-002).

SHA256(source_url + content) prevents duplicate chunks on re-crawl.
Content diffing compares hashes to skip unchanged chunks (saves 70-90% embedding cost).
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ChunkFingerprint:
    """Fingerprint record stored in Cosmos DB for deduplication."""
    chunk_id: str
    fingerprint: str  # SHA256 hex digest
    source_url: str
    source_type: str
    indexed_at: datetime
    content_version: int = 1


def compute_fingerprint(source_url: str, content: str) -> str:
    """Compute SHA256 fingerprint for deduplication."""
    payload = f"{source_url}:{content}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def should_index(
    fingerprint: str,
    existing_fingerprints: dict[str, ChunkFingerprint],
) -> bool:
    """
    Check if a chunk should be indexed.
    
    Returns False if an identical chunk already exists (same fingerprint).
    Returns True if the chunk is new or content has changed.
    """
    if fingerprint not in existing_fingerprints:
        return True  # New chunk
    
    # Existing chunk — content unchanged, skip re-embedding
    return False
