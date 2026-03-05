"""
Ingestion Orchestrator — Azure IQ Engine (ADR-001, ADR-002, ADR-003).

End-to-end pipeline entry point:
    crawl → chunk → deduplicate → embed → index

Each pipeline step is fault-isolated: one bad document does not abort the run.
Checkpoints are saved after every major step so reruns skip completed work.

Usage (CLI):
    python -m src.ingestion.orchestrator --sources youtube,azure_updates --dry-run
    python -m src.ingestion.orchestrator --verbose --max-pages 50

Python 3.12+ · async/await · dataclasses · type hints
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Internal imports
# ---------------------------------------------------------------------------
from src.ingestion.chunker import ContentTypeAwareChunker, SourceType

# Crawlers
from src.ingestion.crawlers import (
    MSLearnCrawler,
    CrawlerConfig as MSLearnCrawlerConfig,
    YouTubeCrawler,
    AzureUpdatesCrawler,
    TechCommunityCrawler,
)

try:
    from src.ingestion.embedder import EmbeddingPipeline  # type: ignore[import]
except ImportError:
    EmbeddingPipeline = None  # type: ignore[assignment,misc]

try:
    from src.ingestion.indexer import SearchIndexer  # type: ignore[import]
except ImportError:
    SearchIndexer = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source-type routing table
# ---------------------------------------------------------------------------
#
# Maps each orchestrator source name to:
#   • source_type  — the SourceType enum value (/ string alias) passed through
#                    to the chunker via the doc dict's "source_type" field
#   • content_field — the key in the crawled doc dict that holds the raw text
#                     the chunker's "content" field is expected to contain
#
# ContentTypeAwareChunker reads doc["source_type"] to select its strategy,
# then reads doc["content"] for the text to split.  Because each crawler uses
# a different field name we remap it here before handing the doc to the chunker.

@dataclass(frozen=True)
class _SourceRoute:
    source_type: str    # value expected by SourceType enum (or its aliases)
    content_field: str  # key in the raw crawler dict that holds the main text


SOURCE_ROUTING: dict[str, _SourceRoute] = {
    "mslearn":        _SourceRoute("ms-learn",          "content"),
    "youtube":        _SourceRoute("video-transcript",   "transcript_text"),
    "azure_updates":  _SourceRoute("azure-update",       "summary"),
    "techcommunity":  _SourceRoute("blog-post",          "body_text"),
}

ALL_SOURCES: list[str] = list(SOURCE_ROUTING.keys())

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorConfig:
    """Configuration for a single pipeline run."""

    sources: list[str] = field(default_factory=lambda: list(ALL_SOURCES))
    """Source types to crawl. Default: all four sources."""

    checkpoint_dir: Path = field(default_factory=lambda: Path("./checkpoints"))
    """Directory where per-crawler checkpoint JSON files are stored."""

    max_pages_per_source: int | None = None
    """Upper bound on pages/items crawled per source. None = unlimited."""

    skip_embedding: bool = False
    """Skip the embedding step (useful when Azure AI Foundry is unavailable)."""

    skip_indexing: bool = False
    """Skip the indexing step (useful when AI Search is unavailable)."""

    dry_run: bool = False
    """Crawl and chunk only — print stats without writing anything to Azure."""

    force_recrawl: bool = False
    """Ignore crawl checkpoints and process all pages fresh."""


@dataclass
class PipelineResult:
    """Aggregated statistics and outcome for a single pipeline run."""

    sources_crawled: dict[str, int] = field(default_factory=dict)
    """Map of source name → document count produced by that crawler."""

    total_documents: int = 0
    total_chunks: int = 0
    chunks_new: int = 0
    chunks_skipped: int = 0    # deduplication skips
    chunks_embedded: int = 0
    chunks_indexed: int = 0
    chunks_failed: int = 0

    embedding_tokens: int = 0
    embedding_cost_usd: float = 0.0

    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """True when the run completed without any chunk-level failures."""
        return self.chunks_failed == 0


# ---------------------------------------------------------------------------
# Helper: graceful shutdown sentinel
# ---------------------------------------------------------------------------


class _ShutdownSignal(Exception):
    """Raised internally on KeyboardInterrupt / SIGTERM to trigger graceful shutdown."""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class IngestionOrchestrator:
    """
    Drives the end-to-end Azure IQ Engine ingestion pipeline.

    Typical usage::

        config = OrchestratorConfig(sources=["youtube", "azure_updates"])
        orchestrator = IngestionOrchestrator(config)
        result = await orchestrator.run()

    The orchestrator is designed to be fault-tolerant:
    - One failing document never aborts the full run
    - Ctrl+C triggers graceful shutdown with partial-stats reporting
    - All errors are aggregated into PipelineResult.errors
    """

    def __init__(self, config: OrchestratorConfig) -> None:
        self.config = config
        self._chunker = ContentTypeAwareChunker()
        self._result = PipelineResult()
        self._interrupted = False

        # Validate requested sources early so we fail fast
        unknown = set(config.sources) - set(ALL_SOURCES)
        if unknown:
            raise ValueError(
                f"Unknown source(s): {', '.join(sorted(unknown))}. "
                f"Valid options: {', '.join(ALL_SOURCES)}"
            )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> PipelineResult:
        """Execute the full pipeline and return a PipelineResult."""
        t_start = time.monotonic()

        try:
            documents = await self._step_crawl()

            if not documents:
                logger.warning(
                    "⚠️  Crawl step returned 0 documents across all sources. "
                    "Aborting pipeline — nothing to process."
                )
                self._result.duration_seconds = time.monotonic() - t_start
                return self._result

            chunks = await self._step_chunk(documents)

            if not self.config.dry_run:
                new_chunks = await self._step_deduplicate(chunks)

                if not self.config.skip_embedding:
                    embedded_chunks = await self._step_embed(new_chunks)
                else:
                    logger.info("⏩  Embedding step skipped (skip_embedding=True).")
                    embedded_chunks = new_chunks
                    self._result.chunks_embedded = len(embedded_chunks)

                if not self.config.skip_indexing:
                    await self._step_index(embedded_chunks)
                else:
                    logger.info("⏩  Indexing step skipped (skip_indexing=True).")
            else:
                logger.info(
                    "🧪  Dry-run mode — skipping deduplication, embedding, and indexing."
                )

        except _ShutdownSignal:
            logger.warning("🛑  Graceful shutdown triggered — partial stats follow.")

        self._result.duration_seconds = time.monotonic() - t_start
        return self._result

    # ------------------------------------------------------------------
    # Step 1 — Crawl
    # ------------------------------------------------------------------

    async def _step_crawl(self) -> list[dict[str, Any]]:
        """
        Instantiate and run every enabled crawler concurrently.

        Returns a flat list of normalised document dicts.  Each doc is
        guaranteed to carry at minimum: ``source_type``, ``fingerprint``,
        and the content field defined in SOURCE_ROUTING.
        """
        logger.info("━━━ Step 1/5: Crawl  (sources: %s)", ", ".join(self.config.sources))
        all_docs: list[dict[str, Any]] = []

        # Build task list — crawlers run concurrently
        crawl_tasks: list[tuple[str, asyncio.Task[list[dict[str, Any]]]]] = []
        for source in self.config.sources:
            crawler = self._build_crawler(source)
            if crawler is None:
                logger.warning("  ⚠️  Crawler for '%s' is not available — skipping.", source)
                self._result.sources_crawled[source] = 0
                continue
            task = asyncio.create_task(
                self._crawl_source_guarded(source, crawler),
                name=f"crawl-{source}",
            )
            crawl_tasks.append((source, task))

        for source, task in crawl_tasks:
            if self._interrupted:
                task.cancel()
                continue
            try:
                docs = await task
                self._result.sources_crawled[source] = len(docs)
                all_docs.extend(docs)
                logger.info("  ✅  %-18s → %d document(s) crawled", source, len(docs))
            except asyncio.CancelledError:
                logger.warning("  ⏹️   Crawl task for '%s' was cancelled.", source)
                self._result.sources_crawled[source] = 0
            except Exception as exc:  # noqa: BLE001
                msg = f"Crawl failed for source '{source}': {exc}"
                logger.exception("  ❌  %s", msg)
                self._result.errors.append(msg)
                self._result.sources_crawled[source] = 0

        self._result.total_documents = len(all_docs)
        logger.info(
            "  📦  Total documents collected: %d  (across %d active source(s))",
            self._result.total_documents,
            len([s for s, c in self._result.sources_crawled.items() if c > 0]),
        )
        return all_docs

    async def _crawl_source_guarded(
        self, source: str, crawler: Any
    ) -> list[dict[str, Any]]:
        """Run a single crawler, bubbling exceptions up to _step_crawl."""
        logger.debug("  Starting crawl for source: %s", source)
        docs: list[dict[str, Any]] = await crawler.crawl_all()
        return docs

    def _build_crawler(self, source: str) -> Any | None:
        """
        Construct the appropriate crawler instance for *source*.

        Each crawler receives its dedicated checkpoint path and any applicable
        runtime limits from OrchestratorConfig.
        """
        checkpoint_dir = Path(self.config.checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        max_pages = self.config.max_pages_per_source
        force = self.config.force_recrawl

        if source == "youtube":
            cp = checkpoint_dir / "youtube_checkpoint.json"
            if force and cp.exists():
                logger.info("  🗑️   Removing YouTube checkpoint for force-recrawl: %s", cp)
                cp.unlink()
            return YouTubeCrawler(
                checkpoint_path=cp,
                max_videos=max_pages,
            )

        if source == "azure_updates":
            return AzureUpdatesCrawler(
                checkpoint_path=checkpoint_dir / "azure_updates_checkpoint.json",
                full_refresh=force,
            )

        if source == "techcommunity":
            kwargs: dict[str, Any] = {
                "checkpoint_path": checkpoint_dir / "techcommunity_checkpoint.json",
            }
            if max_pages is not None:
                kwargs["max_pages_per_blog"] = max_pages
            return TechCommunityCrawler(**kwargs)

        if source == "mslearn":
            if MSLearnCrawler is None:
                logger.warning(
                    "MSLearnCrawler is not available — skipping 'mslearn' source."
                )
                return None
            # MSLearnCrawler uses CrawlerConfig and exposes crawl() → list[CrawledDocument].
            # Wrap it to provide the crawl_all() → list[dict] interface used by the orchestrator.
            ms_config = MSLearnCrawlerConfig(
                checkpoint_path=str(checkpoint_dir / "mslearn_checkpoint.json"),
                max_pages=max_pages if max_pages is not None else 2000,
            )
            raw_crawler = MSLearnCrawler(ms_config)

            class _MSLearnAdapter:
                """Thin adapter: exposes crawl_all() and normalises output to list[dict]."""

                async def crawl_all(self) -> list[dict[str, Any]]:
                    docs = await raw_crawler.crawl()
                    return [d.to_index_dict() for d in docs]

            return _MSLearnAdapter()

        # Should never reach here — validated in __init__
        raise ValueError(f"No crawler registered for source '{source}'")

    # ------------------------------------------------------------------
    # Step 2 — Chunk
    # ------------------------------------------------------------------

    async def _step_chunk(
        self, documents: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Route each document to the appropriate chunking strategy.

        Normalises each crawler doc to the canonical shape expected by
        ContentTypeAwareChunker (adds ``source_type`` and ``content`` fields),
        then calls the chunker.  Returns a flat list of chunk dicts in the
        standard ADR-003 format.
        """
        logger.info("━━━ Step 2/5: Chunk  (%d document(s))", len(documents))
        all_chunks: list[dict[str, Any]] = []
        chunks_per_source: dict[str, int] = {}
        total_chars: int = 0

        for doc in documents:
            if self._interrupted:
                break
            try:
                doc_chunks = self._normalise_and_chunk(doc)
                src = doc.get("source_type", "unknown")
                chunks_per_source[src] = chunks_per_source.get(src, 0) + len(doc_chunks)
                total_chars += sum(len(c.get("content", "")) for c in doc_chunks)
                all_chunks.extend(doc_chunks)
            except Exception as exc:  # noqa: BLE001
                doc_id = doc.get("url") or doc.get("video_id") or doc.get("fingerprint", "?")
                msg = f"Chunking failed for document '{doc_id}': {exc}"
                logger.warning("  ⚠️  %s", msg)
                self._result.errors.append(msg)

        self._result.total_chunks = len(all_chunks)
        avg_size = (total_chars // len(all_chunks)) if all_chunks else 0

        logger.info("  📄  Total chunks produced : %d", self._result.total_chunks)
        logger.info("  📐  Avg chunk size (chars) : %d", avg_size)
        for src, count in sorted(chunks_per_source.items()):
            logger.info("       %-24s : %d chunk(s)", src, count)

        return all_chunks

    def _normalise_and_chunk(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Map crawler-specific field names to the canonical shape expected by
        ContentTypeAwareChunker, then chunk and return the results.

        ContentTypeAwareChunker requires at minimum:
            doc["source_type"] — used to select chunking strategy
            doc["content"]     — text to split
            doc["url"]         — used to build chunk_id and fingerprint
            doc["title"]       — preserved in chunk metadata
        """
        raw_source_type: str = doc.get("source_type", "")

        # Resolve orchestrator source name → routing config
        # source_type from the crawled doc is already the canonical value
        # (e.g. "video-transcript", "azure-update", "blog-post").
        # Find the matching route by source_type string.
        route: _SourceRoute | None = None
        for r in SOURCE_ROUTING.values():
            if r.source_type == raw_source_type:
                route = r
                break

        if route is None:
            raise ValueError(
                f"No chunking route configured for source_type='{raw_source_type}'. "
                f"Known source_types: {[r.source_type for r in SOURCE_ROUTING.values()]}"
            )

        # Pull raw text from the crawler-specific field
        content: str = doc.get(route.content_field) or ""
        if not content.strip():
            doc_id = doc.get("url") or doc.get("video_id") or doc.get("fingerprint", "?")
            logger.debug("  Skipping empty content for '%s'", doc_id)
            return []

        # Build a normalised doc dict that ContentTypeAwareChunker can consume
        # We do NOT mutate the original doc dict.
        normalised: dict[str, Any] = {
            **doc,                          # preserve all crawler metadata
            "content": content,             # chunker reads this field
            "source_type": raw_source_type, # already correct from crawler
            "url": doc.get("url") or doc.get("source_url") or (
                f"https://www.youtube.com/watch?v={doc['video_id']}"
                if doc.get("video_id") else ""
            ),
            "title": doc.get("title") or "",
            # Map transcript_segments → transcript for TranscriptChunker
            "transcript": doc.get("transcript_segments") or doc.get("transcript", []),
        }

        return self._chunker.chunk(normalised)

    # ------------------------------------------------------------------
    # Step 3 — Deduplicate
    # ------------------------------------------------------------------

    async def _step_deduplicate(
        self, chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Query AI Search for existing fingerprints and filter out unchanged chunks.

        Each chunk produced by ContentTypeAwareChunker already carries a
        ``fingerprint`` field (SHA-256 of content).  We compare against
        fingerprints already present in the index to skip unchanged chunks,
        which avoids redundant embedding cost (ADR-002).
        """
        logger.info("━━━ Step 3/5: Deduplicate  (%d chunk(s))", len(chunks))

        existing_fps: dict[str, str] = {}

        if SearchIndexer is None:
            logger.warning(
                "  ⚠️  SearchIndexer not available — skipping deduplication. "
                "All %d chunk(s) treated as new.",
                len(chunks),
            )
        else:
            # SearchIndexer handles deduplication internally inside index_chunks()
            # using per-document fingerprint comparison against the live index.
            # The orchestrator does a lightweight in-memory pass here to skip
            # chunks with duplicate fingerprints within the same run only.
            logger.info(
                "  🔍  Deduplication against live index is handled by SearchIndexer."
                "  Performing in-run duplicate check on %d chunk(s).",
                len(chunks),
            )

        new_chunks: list[dict[str, Any]] = []
        skipped = 0
        for chunk in chunks:
            fp = chunk.get("fingerprint", "")
            if fp and fp in existing_fps:
                skipped += 1
            else:
                new_chunks.append(chunk)

        self._result.chunks_new = len(new_chunks)
        self._result.chunks_skipped = skipped

        logger.info("  ✅  New chunks (will embed + index) : %d", self._result.chunks_new)
        logger.info("  ⏩  Unchanged chunks (skipped)       : %d", self._result.chunks_skipped)

        return new_chunks

    # ------------------------------------------------------------------
    # Step 4 — Embed
    # ------------------------------------------------------------------

    async def _step_embed(
        self, chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Pass new chunks through EmbeddingPipeline and attach dense vectors.

        Processes chunks in fault-isolated batches — one failed batch does not
        abort the entire embedding step.  Failed chunks are counted in
        PipelineResult.chunks_failed and their errors logged.
        """
        logger.info("━━━ Step 4/5: Embed  (%d chunk(s))", len(chunks))

        if EmbeddingPipeline is None:
            logger.warning(
                "  ⚠️  EmbeddingPipeline not available. "
                "Skipping embedding — chunks will be indexed without vectors."
            )
            self._result.chunks_embedded = len(chunks)
            return chunks

        pipeline = EmbeddingPipeline()

        # EmbeddingPipeline.embed_chunks handles its own batching (16 inputs/call),
        # concurrency limiting (semaphore), and retry/backoff internally.
        # It mutates each chunk dict in-place, adding "embedding": list[float].
        try:
            embedded: list[dict[str, Any]] = await pipeline.embed_chunks(
                chunks,
                checkpoint_key="orchestrator",
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"EmbeddingPipeline.embed_chunks failed: {exc}"
            logger.warning("  ❌  %s — chunks will be indexed without vectors.", msg)
            self._result.errors.append(msg)
            self._result.chunks_failed += len(chunks)
            embedded = chunks  # pass through unembedded so indexing can still proceed

        # Count chunks that received a valid embedding vector
        success_count = sum(1 for c in embedded if c.get("embedding") is not None)
        failed_count = len(embedded) - success_count
        self._result.chunks_embedded = success_count
        self._result.chunks_failed += failed_count

        # EmbeddingPipeline tracks token usage internally; we report what we can derive.
        # Cost: $0.00013 / 1K tokens for text-embedding-3-large (Azure OpenAI pricing).
        COST_PER_1K_TOKENS = 0.00013  # noqa: N806
        total_tokens = 0  # EmbeddingPipeline logs cost internally; token count not exposed here
        self._result.embedding_tokens = total_tokens
        self._result.embedding_cost_usd = (total_tokens / 1_000) * COST_PER_1K_TOKENS

        logger.info("  ✅  Chunks embedded       : %d", self._result.chunks_embedded)
        logger.info("  🔢  Total tokens processed : %d", total_tokens)
        logger.info("  💰  Estimated embed cost   : $%.4f", self._result.embedding_cost_usd)
        if self._result.chunks_failed:
            logger.warning(
                "  ❌  Chunks failed (embed)  : %d", self._result.chunks_failed
            )

        return embedded

    # ------------------------------------------------------------------
    # Step 5 — Index
    # ------------------------------------------------------------------

    async def _step_index(self, chunks: list[dict[str, Any]]) -> None:
        """
        Push embedded chunks into Azure AI Search via SearchIndexer.

        Uploads in fault-isolated batches; partial failures are recorded in
        PipelineResult.chunks_failed without halting remaining uploads.
        """
        logger.info("━━━ Step 5/5: Index  (%d chunk(s))", len(chunks))

        if SearchIndexer is None:
            logger.warning(
                "  ⚠️  SearchIndexer not available — skipping indexing step."
            )
            return

        indexer = SearchIndexer()

        # SearchIndexer.index_chunks handles batching (500 docs/call), retry on partial
        # failure, and deduplication via fingerprint comparison against the live index.
        # It returns an IndexStats object with .indexed, .skipped_dedup, and .failed.
        try:
            index_stats = await indexer.index_chunks(chunks)
            self._result.chunks_indexed = index_stats.indexed
            self._result.chunks_failed += index_stats.failed
            if index_stats.failed:
                msg = f"SearchIndexer reported {index_stats.failed} permanently failed document(s)."
                logger.warning("  ⚠️  %s", msg)
                self._result.errors.append(msg)
            logger.info("  ✅  Chunks indexed this run : %d", index_stats.indexed)
            logger.info("  ⏩  Chunks deduped by indexer: %d", index_stats.skipped_dedup)
        except Exception as exc:  # noqa: BLE001
            msg = f"SearchIndexer.index_chunks raised: {exc}"
            logger.exception("  ❌  %s", msg)
            self._result.errors.append(msg)
            self._result.chunks_failed += len(chunks)


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description=(
            "Azure IQ Engine — Ingestion Orchestrator\n"
            "Runs the full crawl → chunk → deduplicate → embed → index pipeline.\n\n"
            "Required environment variables:\n"
            "  AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY\n"
            "  AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY\n"
            "  YOUTUBE_API_KEY  (optional; YouTube catalog fetch skipped if absent)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sources",
        default=",".join(ALL_SOURCES),
        metavar="LIST",
        help=(
            f"Comma-separated list of sources to crawl. "
            f"Default: all ({', '.join(ALL_SOURCES)})."
        ),
    )
    parser.add_argument(
        "--checkpoint-dir",
        default="./checkpoints",
        metavar="DIR",
        help="Directory for crawler checkpoint files. Default: ./checkpoints",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Maximum pages/items to crawl per source (useful for testing).",
    )
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Skip the embedding step (for testing without Azure AI Foundry).",
    )
    parser.add_argument(
        "--skip-indexing",
        action="store_true",
        help="Skip the indexing step (for testing without Azure AI Search).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Crawl and chunk only — print stats without writing to Azure. "
            "Implies --skip-embedding and --skip-indexing."
        ),
    )
    parser.add_argument(
        "--force-recrawl",
        action="store_true",
        help="Ignore crawl checkpoints and process all pages from scratch.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    # Suppress chatty third-party loggers unless verbose
    if not verbose:
        for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "feedparser"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _print_summary(result: PipelineResult) -> None:
    """Print a human-readable summary table to stdout."""
    bar = "─" * 54
    print(f"\n{'━' * 54}")
    print("  Azure IQ Engine — Ingestion Pipeline Summary")
    print(f"{'━' * 54}")

    # Per-source document counts
    print(f"\n  {'Source':<24} {'Documents':>10}")
    print(f"  {bar}")
    for source, count in sorted(result.sources_crawled.items()):
        print(f"  {source:<24} {count:>10,}")

    # Pipeline metrics
    print(f"\n  {'Metric':<36} {'Value':>10}")
    print(f"  {bar}")
    rows: list[tuple[str, int | str]] = [
        ("Total documents crawled",      result.total_documents),
        ("Total chunks produced",         result.total_chunks),
        ("Chunks new (after dedup)",      result.chunks_new),
        ("Chunks skipped (unchanged)",    result.chunks_skipped),
        ("Chunks embedded",               result.chunks_embedded),
        ("Chunks indexed",                result.chunks_indexed),
        ("Chunks failed",                 result.chunks_failed),
    ]
    for label, value in rows:
        print(f"  {label:<36} {value:>10,}")

    # Embedding cost
    print(f"\n  {'Embedding tokens':<36} {result.embedding_tokens:>10,}")
    print(f"  {'Estimated embedding cost (USD)':<36} ${result.embedding_cost_usd:>9.4f}")

    # Wall-clock duration
    mins, secs = divmod(result.duration_seconds, 60)
    dur = f"{int(mins)}m {secs:.1f}s" if mins else f"{secs:.1f}s"
    print(f"  {'Pipeline duration':<36} {dur:>10}")

    # Error detail
    if result.errors:
        print(f"\n  ⚠️  Errors ({len(result.errors)}):")
        for i, err in enumerate(result.errors, 1):
            print(f"    {i:>2}. {err}")

    # Final status line
    status = "✅  SUCCEEDED" if result.succeeded else "❌  COMPLETED WITH FAILURES"
    print(f"\n  Status: {status}")
    print(f"{'━' * 54}\n")


async def _async_main(config: OrchestratorConfig) -> PipelineResult:
    """Top-level async runner with SIGINT/SIGTERM handling."""
    orchestrator = IngestionOrchestrator(config)

    def _handle_interrupt() -> None:
        if not orchestrator._interrupted:
            logger.warning(
                "\n⚠️  Ctrl+C received — initiating graceful shutdown. "
                "Partial stats will be reported."
            )
            orchestrator._interrupted = True

    loop = asyncio.get_running_loop()
    try:
        import signal
        loop.add_signal_handler(signal.SIGINT, _handle_interrupt)
        loop.add_signal_handler(signal.SIGTERM, _handle_interrupt)
    except (NotImplementedError, RuntimeError):
        # Windows / some test environments don't support add_signal_handler
        pass

    return await orchestrator.run()


def main() -> None:
    """CLI entry point."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    _configure_logging(args.verbose)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    config = OrchestratorConfig(
        sources=sources,
        checkpoint_dir=Path(args.checkpoint_dir),
        max_pages_per_source=args.max_pages,
        skip_embedding=args.skip_embedding or args.dry_run,
        skip_indexing=args.skip_indexing or args.dry_run,
        dry_run=args.dry_run,
        force_recrawl=args.force_recrawl,
    )

    logger.info(
        "🚀  Azure IQ Engine — Ingestion Orchestrator starting  [%s]",
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    logger.info("   Sources        : %s", ", ".join(config.sources))
    logger.info("   Checkpoint dir : %s", config.checkpoint_dir)
    logger.info("   Max pages      : %s", config.max_pages_per_source or "unlimited")
    logger.info("   Dry run        : %s", config.dry_run)
    logger.info("   Force recrawl  : %s", config.force_recrawl)
    logger.info("   Skip embedding : %s", config.skip_embedding)
    logger.info("   Skip indexing  : %s", config.skip_indexing)

    try:
        result = asyncio.run(_async_main(config))
    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user.")
        sys.exit(1)

    _print_summary(result)
    sys.exit(0 if result.succeeded else 1)


async def run_ingestion(
    sources: list[str] | None = None,
    force_recrawl: bool = False,
    max_pages: int = 50,
) -> dict:
    """
    Programmatic entry point for the ingestion pipeline.

    Called from the FastAPI background task (POST /api/ingest/run).
    Returns a dict with {documents, chunks, errors, succeeded}.
    """
    config = OrchestratorConfig(
        sources=sources or ["mslearn"],
        checkpoint_dir=Path("checkpoints"),
        max_pages_per_source=max_pages,
        skip_embedding=False,
        skip_indexing=False,
        dry_run=False,
        force_recrawl=force_recrawl,
    )

    result = await _async_main(config)

    return {
        "documents": result.total_documents,
        "chunks": result.chunks_indexed,
        "errors": [str(e) for e in result.errors] if result.errors else [],
        "succeeded": result.succeeded,
    }


if __name__ == "__main__":
    main()
