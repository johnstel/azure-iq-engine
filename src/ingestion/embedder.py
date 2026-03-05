"""
Embedding Pipeline (ADR-004).

Generates embeddings for document chunks via Azure OpenAI (Foundry endpoint).
Model: text-embedding-3-large (1536 dimensions, 8191 token max input).

Features:
- Batched requests (16 inputs/call, Azure OpenAI limit)
- Concurrency-limited (max 5 simultaneous calls via semaphore)
- Exponential backoff on 429 rate-limit responses
- Token budget enforcement with per-chunk truncation
- Cost tracking ($0.00013 / 1K tokens)
- Checkpoint-based resume (every 100 chunks)
- Graceful degradation when FOUNDRY_KEY is absent
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_MODEL_DEPLOYMENT = "text-embedding-3-large"
_API_VERSION = "2024-06-01"
_MAX_TOKENS_PER_INPUT = 8191
_CHARS_PER_TOKEN_APPROX = 4          # rough character-to-token ratio for truncation
_BATCH_SIZE = 16                     # Azure OpenAI embeddings API hard limit
_MAX_CONCURRENT_CALLS = 5
_COST_PER_1K_TOKENS = 0.00013        # USD, text-embedding-3-large
_CHECKPOINT_INTERVAL = 100           # chunks between checkpoint saves
_EMBEDDING_DIMENSIONS = 1536

_BACKOFF_BASE = 1.0                  # seconds
_BACKOFF_MAX = 60.0
_BACKOFF_MULTIPLIER = 2.0
_MAX_RETRIES = 6


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class EmbedderConfig:
    """Runtime configuration resolved from environment variables."""

    foundry_base_url: str = field(
        default_factory=lambda: os.getenv(
            "FOUNDRY_BASE_URL",
            "https://ai-aihubjs102110245342.services.ai.azure.com",
        )
    )
    foundry_key: str | None = field(
        default_factory=lambda: os.getenv("FOUNDRY_KEY")
    )
    model_deployment: str = _MODEL_DEPLOYMENT
    api_version: str = _API_VERSION
    batch_size: int = _BATCH_SIZE
    max_concurrent: int = _MAX_CONCURRENT_CALLS
    checkpoint_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("CHECKPOINT_DIR", "/tmp/iq-engine-checkpoints")
        )
    )

    def embeddings_url(self) -> str:
        base = self.foundry_base_url.rstrip("/")
        return (
            f"{base}/openai/deployments/{self.model_deployment}"
            f"/embeddings?api-version={self.api_version}"
        )


# ── Pipeline ───────────────────────────────────────────────────────────────────

class EmbeddingPipeline:
    """
    Generates and attaches embeddings to document chunks.

    Usage::

        pipeline = EmbeddingPipeline()
        embedded_chunks = await pipeline.embed_chunks(chunks)

    Each chunk dict receives an ``embedding`` key (list of 1536 floats).
    Chunks that cannot be embedded (API failure) retain ``embedding = None``.
    """

    def __init__(self, config: EmbedderConfig | None = None) -> None:
        self._cfg = config or EmbedderConfig()
        self._semaphore = asyncio.Semaphore(self._cfg.max_concurrent)
        self._total_tokens: int = 0
        self._cfg.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────────────────

    async def embed_chunks(
        self,
        chunks: list[dict[str, Any]],
        checkpoint_key: str = "default",
    ) -> list[dict[str, Any]]:
        """
        Embed all chunks, returning the mutated list with ``embedding`` populated.

        :param chunks: List of chunk dicts from the chunker.
        :param checkpoint_key: Unique key used to name the checkpoint file,
                               allowing concurrent jobs without collisions.
        :returns: Same list with ``embedding`` field added to each dict.
        """
        if not self._cfg.foundry_key:
            logger.error(
                "FOUNDRY_KEY not set — returning chunks without embeddings. "
                "Set the environment variable to enable embedding generation."
            )
            return chunks

        # Resume from checkpoint if one exists
        start_index, checkpoint_data = self._load_checkpoint(checkpoint_key, chunks)
        if start_index > 0:
            logger.info(
                "Resuming from checkpoint: %d/%d chunks already embedded.",
                start_index,
                len(chunks),
            )
            # Restore previously saved embeddings
            for i, emb in checkpoint_data.items():
                chunks[int(i)]["embedding"] = emb

        pending = chunks[start_index:]
        if not pending:
            logger.info("All chunks already embedded (checkpoint complete).")
            self._log_cost_summary()
            return chunks

        logger.info(
            "Embedding %d chunks (batch_size=%d, max_concurrent=%d).",
            len(pending),
            self._cfg.batch_size,
            self._cfg.max_concurrent,
        )

        # Truncate over-budget chunks before batching
        pending = [self._enforce_token_budget(c) for c in pending]

        # Process in batches with concurrency control
        batches = _batchify(pending, self._cfg.batch_size)
        embedded_count = start_index

        async with httpx.AsyncClient(timeout=60.0) as client:
            batch_tasks = [
                self._embed_batch(client, batch) for batch in batches
            ]
            # Process concurrently but respect semaphore inside each task
            results: list[list[list[float] | None]] = await asyncio.gather(
                *batch_tasks, return_exceptions=False
            )

        # Attach embeddings and checkpoint periodically
        flat_embeddings = [emb for batch_result in results for emb in batch_result]
        for chunk, embedding in zip(pending, flat_embeddings):
            chunk["embedding"] = embedding
            embedded_count += 1

            if embedded_count % _CHECKPOINT_INTERVAL == 0:
                self._save_checkpoint(checkpoint_key, chunks, embedded_count)
                logger.debug("Checkpoint saved at %d chunks.", embedded_count)

        # Final checkpoint
        self._save_checkpoint(checkpoint_key, chunks, len(chunks))
        self._log_cost_summary()

        success = sum(1 for c in chunks if c.get("embedding") is not None)
        failed = len(chunks) - success
        logger.info(
            "Embedding complete — success: %d, failed: %d, total: %d.",
            success,
            failed,
            len(chunks),
        )
        return chunks

    # ── Internal ────────────────────────────────────────────────────────────────

    async def _embed_batch(
        self,
        client: httpx.AsyncClient,
        batch: list[dict[str, Any]],
    ) -> list[list[float] | None]:
        """
        Call Azure OpenAI embeddings for a single batch with retry/backoff.
        Returns a parallel list of embeddings (or None on persistent failure).
        """
        texts = [c["content"] for c in batch]
        async with self._semaphore:
            for attempt in range(_MAX_RETRIES):
                try:
                    response = await client.post(
                        self._cfg.embeddings_url(),
                        headers={
                            "api-key": self._cfg.foundry_key,
                            "Content-Type": "application/json",
                        },
                        json={"input": texts, "model": self._cfg.model_deployment},
                    )

                    if response.status_code == 429:
                        wait = _backoff_seconds(attempt)
                        logger.warning(
                            "Rate limited (429) on attempt %d/%d — backing off %.1fs.",
                            attempt + 1,
                            _MAX_RETRIES,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue

                    if response.status_code != 200:
                        logger.error(
                            "Embeddings API error %d: %s",
                            response.status_code,
                            response.text[:400],
                        )
                        wait = _backoff_seconds(attempt)
                        await asyncio.sleep(wait)
                        continue

                    payload = response.json()
                    embeddings = [item["embedding"] for item in payload["data"]]

                    # Accumulate token usage
                    usage = payload.get("usage", {})
                    tokens_used = usage.get("total_tokens", 0)
                    self._total_tokens += tokens_used

                    logger.debug(
                        "Batch of %d embedded — %d tokens used.",
                        len(batch),
                        tokens_used,
                    )
                    return embeddings

                except httpx.RequestError as exc:
                    wait = _backoff_seconds(attempt)
                    logger.warning(
                        "Network error on attempt %d/%d: %s — retrying in %.1fs.",
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)

            logger.error(
                "Batch of %d chunks failed after %d attempts — embedding set to None.",
                len(batch),
                _MAX_RETRIES,
            )
            return [None] * len(batch)

    def _enforce_token_budget(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """
        Truncate chunk content if it likely exceeds the model's token budget.

        Uses a character-based heuristic (4 chars ≈ 1 token) to avoid the
        overhead of a full tokenizer for every chunk.
        """
        content = chunk.get("content", "")
        max_chars = _MAX_TOKENS_PER_INPUT * _CHARS_PER_TOKEN_APPROX

        if len(content) > max_chars:
            truncated = content[:max_chars]
            logger.warning(
                "Chunk '%s' truncated from %d to %d chars (exceeds ~%d token budget).",
                chunk.get("chunk_id", "unknown"),
                len(content),
                max_chars,
                _MAX_TOKENS_PER_INPUT,
            )
            chunk = {**chunk, "content": truncated, "_truncated": True}

        return chunk

    # ── Checkpointing ───────────────────────────────────────────────────────────

    def _checkpoint_path(self, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return self._cfg.checkpoint_dir / f"embed_checkpoint_{safe_key}.json"

    def _save_checkpoint(
        self,
        key: str,
        chunks: list[dict[str, Any]],
        embedded_up_to: int,
    ) -> None:
        """Persist current embeddings to disk so an interrupted run can resume."""
        data: dict[str, Any] = {
            "embedded_up_to": embedded_up_to,
            "total_tokens": self._total_tokens,
            "embeddings": {
                str(i): c["embedding"]
                for i, c in enumerate(chunks[:embedded_up_to])
                if c.get("embedding") is not None
            },
        }
        path = self._checkpoint_path(key)
        path.write_text(json.dumps(data), encoding="utf-8")

    def _load_checkpoint(
        self,
        key: str,
        chunks: list[dict[str, Any]],
    ) -> tuple[int, dict[str, list[float]]]:
        """
        Load checkpoint data if available.

        Returns (start_index, {index_str: embedding}) where start_index is the
        first chunk that still needs embedding.
        """
        path = self._checkpoint_path(key)
        if not path.exists():
            return 0, {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            embedded_up_to: int = data.get("embedded_up_to", 0)
            self._total_tokens = data.get("total_tokens", 0)
            embeddings: dict[str, list[float]] = data.get("embeddings", {})

            # Sanity check: chunk count must match
            if embedded_up_to > len(chunks):
                logger.warning(
                    "Checkpoint references %d chunks but current run has %d — ignoring.",
                    embedded_up_to,
                    len(chunks),
                )
                return 0, {}

            logger.info(
                "Checkpoint loaded from %s (%d embeddings).",
                path,
                len(embeddings),
            )
            return embedded_up_to, embeddings

        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Could not parse checkpoint at %s: %s — starting fresh.", path, exc)
            return 0, {}

    # ── Cost reporting ──────────────────────────────────────────────────────────

    def _log_cost_summary(self) -> None:
        cost_usd = (self._total_tokens / 1000) * _COST_PER_1K_TOKENS
        logger.info(
            "Embedding cost summary — total tokens: %d, estimated cost: $%.6f USD.",
            self._total_tokens,
            cost_usd,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _batchify(items: list[Any], size: int) -> list[list[Any]]:
    """Split a list into consecutive batches of up to `size` items."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _backoff_seconds(attempt: int) -> float:
    """Compute exponential backoff duration, capped at _BACKOFF_MAX."""
    return min(_BACKOFF_BASE * (_BACKOFF_MULTIPLIER**attempt), _BACKOFF_MAX)
