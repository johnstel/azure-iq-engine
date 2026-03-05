"""
AI Search Indexer (ADR-005).

Pushes embedded document chunks into Azure AI Search using the REST API.
Supports upsert semantics, deduplication via fingerprint pre-check,
batched uploads, single retry on partial failure, and detailed stats logging.

Index name: ``iq-engine-index`` (configurable via ``SearchIndexerConfig``).
API version: ``2024-07-01``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from .fingerprint import ChunkFingerprint

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_API_VERSION = "2024-07-01"
_DEFAULT_INDEX = "iq-engine-index"
_UPLOAD_BATCH_SIZE = 500      # AI Search max is 1000; 500 for safety margin
_DEDUP_PAGE_SIZE = 1000       # fingerprint fetch page size
_MAX_RETRIES = 1              # single retry for persistent failures

# Fields that contain multi-value string collections in the AI Search schema
_COLLECTION_FIELDS = {"iq_layers", "azure_services", "capabilities", "entities", "target_roles", "certification_tags"}

# The special "@search.action" key required by AI Search batch upload
_MERGE_OR_UPLOAD = "mergeOrUpload"


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class SearchIndexerConfig:
    """Runtime configuration resolved from environment variables."""

    search_endpoint: str = field(
        default_factory=lambda: os.getenv("SEARCH_ENDPOINT", "")
    )
    search_api_key: str | None = field(
        default_factory=lambda: os.getenv("SEARCH_API_KEY")
    )
    index_name: str = _DEFAULT_INDEX
    api_version: str = _API_VERSION
    batch_size: int = _UPLOAD_BATCH_SIZE

    def index_url(self, path: str = "") -> str:
        base = self.search_endpoint.rstrip("/")
        return f"{base}/indexes/{self.index_name}/{path}?api-version={self.api_version}"

    def docs_index_url(self) -> str:
        return self.index_url("docs/index")

    def docs_search_url(self) -> str:
        return self.index_url("docs/search")


# ── Indexer ────────────────────────────────────────────────────────────────────

@dataclass
class IndexStats:
    """Mutable stats accumulator for a single indexing run."""
    total: int = 0
    indexed: int = 0
    skipped_dedup: int = 0
    failed: int = 0

    def log(self) -> None:
        logger.info(
            "Indexing complete — total: %d | indexed: %d | "
            "skipped (dedup): %d | failed: %d.",
            self.total,
            self.indexed,
            self.skipped_dedup,
            self.failed,
        )


class SearchIndexer:
    """
    Uploads embedded chunks to Azure AI Search with upsert semantics.

    Usage::

        indexer = SearchIndexer()
        stats = await indexer.index_chunks(embedded_chunks)

    Deduplication is performed by fetching all existing fingerprints from the
    index before uploading.  Chunks whose fingerprint is already present are
    skipped, saving index operations cost.

    Failed documents are retried once; persistent failures are logged by
    ``chunk_id`` for manual inspection.
    """

    def __init__(self, config: SearchIndexerConfig | None = None) -> None:
        self._cfg = config or SearchIndexerConfig()

    # ── Public API ──────────────────────────────────────────────────────────────

    async def index_chunks(
        self,
        chunks: list[dict[str, Any]],
    ) -> IndexStats:
        """
        Index all provided chunks into Azure AI Search.

        :param chunks: Embedded chunk dicts (must include ``chunk_id``,
                       ``content``, and optionally ``embedding`` / ``fingerprint``).
        :returns: :class:`IndexStats` with counts for indexed/skipped/failed.
        :raises RuntimeError: If ``SEARCH_ENDPOINT`` or ``SEARCH_API_KEY`` are
                              not configured.
        """
        self._validate_config()

        stats = IndexStats(total=len(chunks))
        logger.info(
            "Starting indexing run — %d chunks to process, index: '%s'.",
            len(chunks),
            self._cfg.index_name,
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Step 1: Fetch existing fingerprints for deduplication
            existing_fingerprints = await self._fetch_existing_fingerprints(client)
            logger.info(
                "Fetched %d existing fingerprints from index.",
                len(existing_fingerprints),
            )

            # Step 2: Filter out chunks that haven't changed
            to_index, skipped = self._apply_dedup(chunks, existing_fingerprints)
            stats.skipped_dedup = skipped
            logger.info(
                "Deduplication: %d to index, %d skipped.",
                len(to_index),
                skipped,
            )

            if not to_index:
                logger.info("No new or updated chunks — nothing to index.")
                stats.log()
                return stats

            # Step 3: Batch upload with retry
            batches = _batchify(to_index, self._cfg.batch_size)
            for batch_num, batch in enumerate(batches, start=1):
                logger.debug(
                    "Uploading batch %d/%d (%d docs).",
                    batch_num,
                    len(batches),
                    len(batch),
                )
                indexed, failed_ids = await self._upload_batch(client, batch)
                stats.indexed += indexed
                stats.failed += len(failed_ids)

                if failed_ids:
                    logger.error(
                        "Batch %d/%d — %d documents failed permanently. "
                        "chunk_ids: %s",
                        batch_num,
                        len(batches),
                        len(failed_ids),
                        failed_ids,
                    )

        stats.log()
        return stats

    # ── Deduplication ───────────────────────────────────────────────────────────

    async def _fetch_existing_fingerprints(
        self,
        client: httpx.AsyncClient,
    ) -> dict[str, str]:
        """
        Retrieve all ``chunk_id → fingerprint`` pairs stored in the index.

        Uses ``$select`` to avoid fetching heavy fields (content, embedding).
        Paginates via ``@odata.nextLink`` until all results are consumed.

        :returns: Dict mapping chunk_id → fingerprint.
        """
        fingerprints: dict[str, str] = {}
        url = self._cfg.docs_search_url()
        payload: dict[str, Any] = {
            "search": "*",
            "select": "chunk_id,fingerprint",
            "top": _DEDUP_PAGE_SIZE,
        }

        while url:
            try:
                response = await client.post(
                    url,
                    headers=self._auth_headers(),
                    json=payload,
                )
                if response.status_code == 404:
                    # Index doesn't exist yet — nothing to deduplicate against
                    logger.info(
                        "Index '%s' not found — treating all chunks as new.",
                        self._cfg.index_name,
                    )
                    return {}

                response.raise_for_status()
                data = response.json()

                for doc in data.get("value", []):
                    chunk_id = doc.get("chunk_id")
                    fp = doc.get("fingerprint")
                    if chunk_id and fp:
                        fingerprints[chunk_id] = fp

                # Follow continuation token if present
                next_link = data.get("@odata.nextLink")
                url = next_link if next_link else None
                # Subsequent pages use GET with the nextLink URL directly
                payload = {}  # nextLink carries all params already

            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Could not fetch existing fingerprints (HTTP %d): %s — "
                    "proceeding without deduplication.",
                    exc.response.status_code,
                    exc.response.text[:300],
                )
                return {}
            except httpx.RequestError as exc:
                logger.warning(
                    "Network error fetching fingerprints: %s — "
                    "proceeding without deduplication.",
                    exc,
                )
                return {}

        return fingerprints

    def _apply_dedup(
        self,
        chunks: list[dict[str, Any]],
        existing: dict[str, str],
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Partition chunks into (to_index, skip_count) based on fingerprint comparison.

        A chunk is skipped when its ``fingerprint`` matches what is already stored
        in the index for the same ``chunk_id``.
        """
        to_index: list[dict[str, Any]] = []
        skip_count = 0

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            new_fp = chunk.get("fingerprint")

            if chunk_id and new_fp and existing.get(chunk_id) == new_fp:
                skip_count += 1
                logger.debug("Skipping unchanged chunk '%s'.", chunk_id)
            else:
                to_index.append(chunk)

        return to_index, skip_count

    # ── Upload ──────────────────────────────────────────────────────────────────

    async def _upload_batch(
        self,
        client: httpx.AsyncClient,
        batch: list[dict[str, Any]],
    ) -> tuple[int, list[str]]:
        """
        Upload a batch of chunks, retrying failed documents once.

        :returns: (indexed_count, list_of_persistently_failed_chunk_ids)
        """
        documents = [self._map_to_search_doc(c) for c in batch]
        indexed, failed_ids = await self._post_batch(client, documents)

        if failed_ids:
            logger.info(
                "Retrying %d failed documents from batch.", len(failed_ids)
            )
            retry_docs = [d for d in documents if d.get("chunk_id") in failed_ids]
            retry_indexed, persistent_failures = await self._post_batch(
                client, retry_docs
            )
            indexed += retry_indexed
            return indexed, persistent_failures

        return indexed, []

    async def _post_batch(
        self,
        client: httpx.AsyncClient,
        documents: list[dict[str, Any]],
    ) -> tuple[int, list[str]]:
        """
        POST a batch to the AI Search index upload endpoint.

        Parses per-document status codes from the response to distinguish
        success (2xx) from failure, enabling targeted retry.

        :returns: (success_count, list_of_failed_chunk_ids)
        """
        payload = {"value": documents}
        try:
            response = await client.post(
                self._cfg.docs_index_url(),
                headers=self._auth_headers(),
                json=payload,
            )
        except httpx.RequestError as exc:
            logger.error("Network error during batch upload: %s", exc)
            # Treat all as failed
            return 0, [d.get("chunk_id", "unknown") for d in documents]

        # AI Search returns 200 even for partial failures; inspect per-doc status
        if response.status_code not in (200, 207):
            logger.error(
                "Batch upload HTTP %d: %s",
                response.status_code,
                response.text[:400],
            )
            return 0, [d.get("chunk_id", "unknown") for d in documents]

        data = response.json()
        results: list[dict[str, Any]] = data.get("value", [])

        success_count = 0
        failed_ids: list[str] = []

        for result in results:
            status_code = result.get("statusCode", 0)
            key = result.get("key", "unknown")
            if 200 <= status_code < 300:
                success_count += 1
                logger.debug("Indexed document '%s' (HTTP %d).", key, status_code)
            else:
                failed_ids.append(key)
                logger.warning(
                    "Document '%s' failed with status %d: %s",
                    key,
                    status_code,
                    result.get("errorMessage", ""),
                )

        logger.info(
            "Batch result — success: %d, failed: %d.",
            success_count,
            len(failed_ids),
        )
        return success_count, failed_ids

    # ── Field mapping ───────────────────────────────────────────────────────────

    def _map_to_search_doc(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """
        Map a chunk dict to the AI Search document schema.

        - ``chunk_id``    → key field (required, string)
        - ``content``     → full-text searchable field
        - ``embedding``   → vector field (Collection(Edm.Single))
        - ``iq_layers``   → Collection(Edm.String) — normalised to list
        - ``azure_services`` → Collection(Edm.String) — normalised to list
        - All other metadata fields are passed through by name.

        The ``@search.action`` key instructs AI Search to use upsert semantics.
        """
        doc: dict[str, Any] = {"@search.action": _MERGE_OR_UPLOAD}

        for key, value in chunk.items():
            if key in _COLLECTION_FIELDS:
                doc[key] = _ensure_string_collection(value)
            else:
                doc[key] = value

        # Embedding must be a flat list of floats (or omitted if None)
        if chunk.get("embedding") is None:
            doc.pop("embedding", None)

        return doc

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _validate_config(self) -> None:
        if not self._cfg.search_endpoint:
            raise RuntimeError(
                "SEARCH_ENDPOINT environment variable is not set. "
                "Example: https://srch-iq-engine-dev.search.windows.net"
            )
        if not self._cfg.search_api_key:
            raise RuntimeError(
                "SEARCH_API_KEY environment variable is not set."
            )

    def _auth_headers(self) -> dict[str, str]:
        return {
            "api-key": self._cfg.search_api_key or "",
            "Content-Type": "application/json",
        }


# ── Module helpers ─────────────────────────────────────────────────────────────

def _batchify(items: list[Any], size: int) -> list[list[Any]]:
    """Split a list into consecutive sublists of up to `size` items."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _ensure_string_collection(value: Any) -> list[str]:
    """
    Normalise a value to ``Collection(Edm.String)`` compatible list.

    Handles None, bare string, and existing list inputs.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return [str(value)]
