"""
Content-Type-Aware Chunker (ADR-003).

Different content types require different chunking strategies.
Universal 512/128 chunking is replaced with per-source-type strategies:

- DocumentChunker   → MS Learn pages, Tech Community posts, blogs, architecture patterns
- TranscriptChunker → YouTube transcripts (timestamp-aware)
- AtomicChunker     → Azure Updates RSS items (no splitting)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token counting — tiktoken preferred, word-count approximation as fallback
# ---------------------------------------------------------------------------

try:
    import tiktoken

    _enc = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_enc.encode(text))

    logger.debug("tiktoken loaded — using cl100k_base encoder")

except Exception:  # pragma: no cover — tiktoken optional dep
    logger.warning(
        "tiktoken not available — falling back to word-count approximation "
        "(len(text.split()) * 1.3).  Install tiktoken for accurate counts."
    )

    def _count_tokens(text: str) -> int:  # type: ignore[misc]
        return int(len(text.split()) * 1.3)


# ---------------------------------------------------------------------------
# Enums & configuration
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    MS_LEARN = "ms-learn"
    TECH_COMMUNITY = "tech-community"
    VIDEO_TRANSCRIPT = "video-transcript"
    AZURE_UPDATE = "azure-update"
    BLOG_POST = "blog-post"
    ARCHITECTURE_PATTERN = "architecture"
    CODE_SAMPLE = "code-sample"

    # Convenience aliases accepted from crawlers
    @classmethod
    def _missing_(cls, value: object) -> "SourceType | None":
        aliases: dict[str, SourceType] = {
            "mslearn": cls.MS_LEARN,
            "learn": cls.MS_LEARN,
            "techcommunity": cls.TECH_COMMUNITY,
            "community": cls.TECH_COMMUNITY,
            "youtube": cls.VIDEO_TRANSCRIPT,
            "transcript": cls.VIDEO_TRANSCRIPT,
            "rss": cls.AZURE_UPDATE,
            "update": cls.AZURE_UPDATE,
            "blog": cls.BLOG_POST,
            "arch": cls.ARCHITECTURE_PATTERN,
            "code": cls.CODE_SAMPLE,
        }
        if isinstance(value, str):
            return aliases.get(value.lower().replace("-", "").replace("_", ""))
        return None


@dataclass
class ChunkConfig:
    """Per-strategy chunking parameters."""

    max_chunk_tokens: int = 512
    overlap_tokens: int = 128
    # TranscriptChunker: gap in seconds that triggers a topic boundary
    topic_gap_seconds: float = 30.0


# ---------------------------------------------------------------------------
# Chunk helpers
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_id(source_url: str, chunk_index: int) -> str:
    return _sha256(f"{source_url}:{chunk_index}")


def _make_chunk(
    *,
    source_url: str,
    source_type: str,
    title: str,
    content: str,
    heading_path: str = "",
    chunk_index: int = 0,
    total_chunks: int = 1,
    video_id: str | None = None,
    video_start_time: float | None = None,
    video_end_time: float | None = None,
    iq_layers: list[str] | None = None,
    azure_services: list[str] | None = None,
    published_at: str = "",
) -> dict[str, Any]:
    content = content.strip()
    return {
        "chunk_id": _chunk_id(source_url, chunk_index),
        "source_url": source_url,
        "source_type": source_type,
        "title": title,
        "content": content,
        "heading_path": heading_path,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,  # patched later by caller
        "token_count": _count_tokens(content),
        "video_id": video_id,
        "video_start_time": video_start_time,
        "video_end_time": video_end_time,
        "iq_layers": iq_layers or [],
        "azure_services": azure_services or [],
        "fingerprint": _sha256(content),
        "published_at": published_at,
    }


def _patch_total_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(chunks)
    for c in chunks:
        c["total_chunks"] = n
    return chunks


# ---------------------------------------------------------------------------
# Sentence splitter (abbreviation-aware)
# ---------------------------------------------------------------------------

# Common abbreviations that contain a period but are NOT sentence endings.
_ABBREVIATIONS: frozenset[str] = frozenset(
    [
        "e.g",
        "i.e",
        "etc",
        "vs",
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sr",
        "jr",
        "no",
        "fig",
        "approx",
        "dept",
        "est",
        "inc",
        "ltd",
        "corp",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
        "st",
        "ave",
        "blvd",
    ]
)

# Sentence boundary: `.`, `?`, `!` followed by whitespace + capital letter
_SENTENCE_BOUNDARY = re.compile(r'([.?!])\s+(?=[A-Z"\'(\[])')


def _split_sentences(text: str) -> list[str]:
    """
    Split *text* into sentences, preserving abbreviation periods.
    Returns a list of sentence strings (with their trailing punctuation).
    """
    # We'll do a token-replace trick: mask known abbreviations, split, unmask.
    masked = text
    placeholders: list[tuple[str, str]] = []
    for abbr in _ABBREVIATIONS:
        pattern = re.compile(r"\b" + re.escape(abbr) + r"\.", re.IGNORECASE)
        for m in pattern.finditer(masked):
            token = f"__ABBR_{len(placeholders)}__"
            placeholders.append((token, m.group()))
        masked = pattern.sub(
            lambda m, _abbr=abbr: f"__ABBR_{len(placeholders) - 1}__",  # noqa
            masked,
        )

    # Re-do masking cleanly (avoid closure issues with lambdas in loop)
    masked = text
    for i, abbr in enumerate(_ABBREVIATIONS):
        safe = list(_ABBREVIATIONS)
        pattern = re.compile(r"\b" + re.escape(abbr) + r"\.", re.IGNORECASE)
        masked = pattern.sub(f"__ABBR_{abbr.upper().replace('.', '_')}__", masked)

    parts = _SENTENCE_BOUNDARY.split(masked)
    sentences: list[str] = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        if i + 1 < len(parts) and parts[i + 1] in ".?!":
            chunk = chunk + parts[i + 1]
            i += 2
        else:
            i += 1
        # Restore abbreviations
        for abbr in _ABBREVIATIONS:
            placeholder = f"__ABBR_{abbr.upper().replace('.', '_')}__"
            chunk = chunk.replace(placeholder, abbr + ".")
        s = chunk.strip()
        if s:
            sentences.append(s)

    return sentences if sentences else [text.strip()]


# ---------------------------------------------------------------------------
# Code-block extraction helpers
# ---------------------------------------------------------------------------

_CODE_FENCE = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)", re.MULTILINE)


@dataclass
class _Block:
    """A logical segment of a markdown document — either plain text or a code block."""

    is_code: bool
    text: str


def _split_code_blocks(text: str) -> list[_Block]:
    """
    Split *text* into alternating plain-text and fenced-code-block segments.
    Code blocks are never split further.
    """
    blocks: list[_Block] = []
    pos = 0
    for m in _CODE_FENCE.finditer(text):
        before = text[pos : m.start()]
        if before:
            blocks.append(_Block(is_code=False, text=before))
        blocks.append(_Block(is_code=True, text=m.group()))
        pos = m.end()
    tail = text[pos:]
    if tail:
        blocks.append(_Block(is_code=False, text=tail))
    return blocks


# ---------------------------------------------------------------------------
# DocumentChunker — MS Learn, Tech Community, Blog, Architecture
# ---------------------------------------------------------------------------


class DocumentChunker:
    """
    Hierarchy-preserving chunker for long-form markdown documents.

    Strategy (ADR-003):
    1. Split on markdown headings (##, ###, …) — each section is a candidate chunk.
    2. If a section exceeds *max_chunk_tokens*, split further on paragraph boundaries.
    3. If a paragraph still exceeds the limit, split on sentence boundaries.
    4. Code blocks are atomic — never split mid-fence.
    5. Add *overlap_tokens* of overlap between consecutive chunks.
    6. Preserve heading hierarchy as a context prefix on every chunk.
    """

    # Matches lines that start with one or more `#` (headings)
    _HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def __init__(self, config: ChunkConfig | None = None) -> None:
        self.config = config or ChunkConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Chunk a crawled document dict into the standard chunk format.

        Expected keys in *doc*:
            url, source_type, title, content (markdown),
            iq_layers, azure_services, published_at
        """
        source_url: str = doc.get("url", "")
        source_type: str = doc.get("source_type", SourceType.MS_LEARN)
        title: str = doc.get("title", "")
        raw_content: str = doc.get("content", "")
        iq_layers: list[str] = doc.get("iq_layers", [])
        azure_services: list[str] = doc.get("azure_services", [])
        published_at: str = doc.get("published_at", "")

        if not raw_content.strip():
            logger.warning("DocumentChunker: empty content for %s", source_url)
            return []

        sections = self._split_into_sections(raw_content)
        raw_chunks: list[tuple[str, str]] = []  # (heading_path, text)

        for heading_path, section_text in sections:
            raw_chunks.extend(
                self._split_section(heading_path, section_text)
            )

        # Apply overlap
        overlapped = self._apply_overlap(raw_chunks)

        chunks: list[dict[str, Any]] = []
        for idx, (heading_path, content) in enumerate(overlapped):
            chunks.append(
                _make_chunk(
                    source_url=source_url,
                    source_type=str(source_type),
                    title=title,
                    content=content,
                    heading_path=heading_path,
                    chunk_index=idx,
                    iq_layers=iq_layers,
                    azure_services=azure_services,
                    published_at=published_at,
                )
            )

        return _patch_total_chunks(chunks)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_into_sections(
        self, text: str
    ) -> list[tuple[str, str]]:
        """
        Split markdown text on headings, **skipping headings inside code blocks**.

        Returns a list of (heading_path, section_body) tuples.
        heading_path follows "## Section > ### Sub > #### SubSub".
        Content before the first heading is treated as a preamble (empty path).
        """
        heading_stack: list[tuple[int, str]] = []  # (level, heading text)
        sections: list[tuple[str, str]] = []
        current_heading_path = ""
        current_lines: list[str] = []
        in_code = False
        fence_marker = ""          # the opening fence string, e.g. "```" or "~~~"

        for line in text.splitlines():
            stripped = line.strip()

            # ── Code-fence toggle ──────────────────────────────────────────
            if not in_code:
                if stripped.startswith("```") or stripped.startswith("~~~"):
                    in_code = True
                    fence_marker = "```" if stripped.startswith("```") else "~~~"
                    current_lines.append(line)
                    continue
            else:
                if stripped.startswith(fence_marker):
                    in_code = False
                    fence_marker = ""
                current_lines.append(line)
                continue

            # ── Heading detection (only outside code blocks) ───────────────
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                # Flush accumulated lines as a section
                section_text = "\n".join(current_lines).strip()
                if section_text or sections:
                    sections.append((current_heading_path, section_text))

                level = len(m.group(1))
                heading_text = m.group(2).strip()
                heading_stack = [(l, h) for (l, h) in heading_stack if l < level]
                heading_stack.append((level, heading_text))
                current_heading_path = " > ".join(
                    f"{'#' * l} {h}" for l, h in heading_stack
                )
                current_lines = []
            else:
                current_lines.append(line)

        # Flush remaining lines
        tail = "\n".join(current_lines).strip()
        if tail:
            sections.append((current_heading_path, tail))

        return sections

    def _split_section(
        self, heading_path: str, section_text: str
    ) -> list[tuple[str, str]]:
        """
        Split a single section into sub-chunks that respect the token limit.
        Code blocks are preserved atomically.
        """
        max_tok = self.config.max_chunk_tokens

        # Separate code blocks from prose
        blocks = _split_code_blocks(section_text)

        # Accumulate sub-chunks
        result: list[tuple[str, str]] = []
        current_parts: list[str] = []
        current_tokens = 0

        def flush() -> None:
            nonlocal current_parts, current_tokens
            text = "\n\n".join(current_parts).strip()
            if text:
                result.append((heading_path, text))
            current_parts = []
            current_tokens = 0

        for block in blocks:
            block_tok = _count_tokens(block.text)

            if block.is_code:
                # Code blocks are atomic — if they're oversized, keep as-is
                if current_tokens + block_tok > max_tok and current_parts:
                    flush()
                current_parts.append(block.text)
                current_tokens += block_tok
            else:
                # Plain prose — try paragraph-level splitting
                paragraphs = [p.strip() for p in re.split(r"\n\n+", block.text) if p.strip()]
                for para in paragraphs:
                    para_tok = _count_tokens(para)

                    if para_tok > max_tok:
                        # Para still too large — split at sentence level
                        if current_parts:
                            flush()
                        result.extend(
                            (heading_path, s)
                            for s in self._split_by_sentence(para)
                        )
                    elif current_tokens + para_tok > max_tok:
                        flush()
                        current_parts.append(para)
                        current_tokens = para_tok
                    else:
                        current_parts.append(para)
                        current_tokens += para_tok

        flush()
        return result if result else [(heading_path, section_text.strip())]

    def _split_by_sentence(self, text: str) -> list[str]:
        """
        Split oversized text at sentence boundaries, grouping sentences up
        to the token limit.  Returns list of chunk strings.
        """
        max_tok = self.config.max_chunk_tokens
        sentences = _split_sentences(text)

        groups: list[str] = []
        current: list[str] = []
        current_tok = 0

        for sent in sentences:
            sent_tok = _count_tokens(sent)
            if sent_tok > max_tok:
                # Single sentence exceeds limit — hard-split at word level
                if current:
                    groups.append(" ".join(current))
                    current = []
                    current_tok = 0
                groups.extend(self._hard_split(sent))
            elif current_tok + sent_tok > max_tok:
                groups.append(" ".join(current))
                current = [sent]
                current_tok = sent_tok
            else:
                current.append(sent)
                current_tok += sent_tok

        if current:
            groups.append(" ".join(current))

        return [g.strip() for g in groups if g.strip()]

    def _hard_split(self, text: str) -> list[str]:
        """Last-resort word-level splitter for extremely long single sentences."""
        max_tok = self.config.max_chunk_tokens
        words = text.split()
        groups: list[str] = []
        current: list[str] = []
        current_tok = 0

        for word in words:
            w_tok = _count_tokens(word)
            if current_tok + w_tok > max_tok and current:
                groups.append(" ".join(current))
                current = [word]
                current_tok = w_tok
            else:
                current.append(word)
                current_tok += w_tok

        if current:
            groups.append(" ".join(current))
        return groups

    def _apply_overlap(
        self, chunks: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """
        Prepend *overlap_tokens* of text from the previous chunk to each chunk
        (except the first).  The heading path stays unchanged per chunk.
        """
        overlap_tok = self.config.overlap_tokens
        if overlap_tok <= 0 or len(chunks) < 2:
            return chunks

        result: list[tuple[str, str]] = [chunks[0]]

        for i in range(1, len(chunks)):
            prev_heading, prev_text = chunks[i - 1]
            cur_heading, cur_text = chunks[i]

            # Take the tail of the previous chunk's text
            prev_words = prev_text.split()
            overlap_words: list[str] = []
            tok_count = 0
            for word in reversed(prev_words):
                w_tok = _count_tokens(word)
                if tok_count + w_tok > overlap_tok:
                    break
                overlap_words.insert(0, word)
                tok_count += w_tok

            overlap_text = " ".join(overlap_words).strip()
            merged = f"{overlap_text}\n\n{cur_text}" if overlap_text else cur_text
            result.append((cur_heading, merged))

        return result


# ---------------------------------------------------------------------------
# TranscriptChunker — YouTube video transcripts
# ---------------------------------------------------------------------------


@dataclass
class _TranscriptSegment:
    """Normalised representation of one transcript segment."""

    text: str
    start_time: float
    end_time: float


class TranscriptChunker:
    """
    Timestamp-aware chunker for YouTube transcripts.

    Strategy (ADR-003):
    - A gap of > *topic_gap_seconds* between consecutive segments signals a
      topic boundary and forces a new chunk.
    - Within a topic, segments are grouped until *max_chunk_tokens* is reached.
    - Each chunk records video_start_time / video_end_time for deep-linking.
    - Chunk text is prefixed with "{video_title} | {timestamp_range}".
    """

    def __init__(self, config: ChunkConfig | None = None) -> None:
        self.config = config or ChunkConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Chunk a transcript document dict.

        Expected keys in *doc*:
            url, source_type, title, video_id,
            transcript (list[dict] with keys: text, start, end or duration),
            iq_layers, azure_services, published_at
        """
        source_url: str = doc.get("url", "")
        source_type: str = doc.get("source_type", SourceType.VIDEO_TRANSCRIPT)
        title: str = doc.get("title", "")
        video_id: str | None = doc.get("video_id")
        iq_layers: list[str] = doc.get("iq_layers", [])
        azure_services: list[str] = doc.get("azure_services", [])
        published_at: str = doc.get("published_at", "")

        raw_segments: list[dict[str, Any]] = doc.get("transcript", [])
        if not raw_segments:
            # Fall back to plain-text content if no structured transcript
            content: str = doc.get("content", "")
            if content.strip():
                logger.warning(
                    "TranscriptChunker: no structured transcript for %s — "
                    "falling back to plain-text chunking",
                    source_url,
                )
                return self._chunk_plain_text(
                    source_url, source_type, title, video_id,
                    content, iq_layers, azure_services, published_at,
                )
            logger.warning("TranscriptChunker: empty transcript for %s", source_url)
            return []

        segments = self._normalise_segments(raw_segments)
        groups = self._group_segments(segments)

        chunks: list[dict[str, Any]] = []
        for idx, seg_group in enumerate(groups):
            chunk_text = self._format_group(title, seg_group)
            chunks.append(
                _make_chunk(
                    source_url=source_url,
                    source_type=str(source_type),
                    title=title,
                    content=chunk_text,
                    heading_path="",
                    chunk_index=idx,
                    video_id=video_id,
                    video_start_time=seg_group[0].start_time,
                    video_end_time=seg_group[-1].end_time,
                    iq_layers=iq_layers,
                    azure_services=azure_services,
                    published_at=published_at,
                )
            )

        return _patch_total_chunks(chunks)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalise_segments(
        self, raw: list[dict[str, Any]]
    ) -> list[_TranscriptSegment]:
        """
        Accept multiple transcript formats:
          - {"text": ..., "start": float, "end": float}
          - {"text": ..., "start": float, "duration": float}
          - {"text": ..., "start_time": float, "end_time": float}
        """
        segs: list[_TranscriptSegment] = []
        for item in raw:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            start = float(
                item.get("start", item.get("start_time", 0.0))
            )
            if "end" in item:
                end = float(item["end"])
            elif "end_time" in item:
                end = float(item["end_time"])
            elif "duration" in item:
                end = start + float(item["duration"])
            else:
                end = start
            segs.append(_TranscriptSegment(text=text, start_time=start, end_time=end))
        return segs

    def _group_segments(
        self, segments: list[_TranscriptSegment]
    ) -> list[list[_TranscriptSegment]]:
        """
        Group segments into topic-coherent chunks.

        A new group starts when:
        - The time gap from the previous segment exceeds *topic_gap_seconds*, OR
        - Adding the next segment would exceed *max_chunk_tokens*.
        """
        if not segments:
            return []

        max_tok = self.config.max_chunk_tokens
        gap_sec = self.config.topic_gap_seconds

        groups: list[list[_TranscriptSegment]] = []
        current: list[_TranscriptSegment] = [segments[0]]
        current_tok = _count_tokens(segments[0].text)

        for prev, curr in zip(segments, segments[1:]):
            time_gap = curr.start_time - prev.end_time
            seg_tok = _count_tokens(curr.text)
            topic_break = time_gap > gap_sec

            if topic_break or (current_tok + seg_tok > max_tok):
                groups.append(current)
                current = [curr]
                current_tok = seg_tok
            else:
                current.append(curr)
                current_tok += seg_tok

        groups.append(current)
        return groups

    def _format_group(
        self, video_title: str, group: list[_TranscriptSegment]
    ) -> str:
        """Build the chunk text: header prefix + concatenated segment text."""
        start_ts = self._fmt_timestamp(group[0].start_time)
        end_ts = self._fmt_timestamp(group[-1].end_time)
        header = f"{video_title} | {start_ts} – {end_ts}"
        body = " ".join(s.text for s in group)
        return f"{header}\n\n{body}"

    @staticmethod
    def _fmt_timestamp(seconds: float) -> str:
        """Format seconds as MM:SS or H:MM:SS."""
        total = int(seconds)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _chunk_plain_text(
        self,
        source_url: str,
        source_type: str,
        title: str,
        video_id: str | None,
        content: str,
        iq_layers: list[str],
        azure_services: list[str],
        published_at: str,
    ) -> list[dict[str, Any]]:
        """Fallback: chunk unstructured transcript text by paragraph / sentence."""
        max_tok = self.config.max_chunk_tokens
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        doc_chunker = DocumentChunker(self.config)

        groups: list[str] = []
        current: list[str] = []
        current_tok = 0
        for para in paragraphs:
            para_tok = _count_tokens(para)
            if para_tok > max_tok:
                if current:
                    groups.append("\n\n".join(current))
                    current = []
                    current_tok = 0
                groups.extend(doc_chunker._split_by_sentence(para))
            elif current_tok + para_tok > max_tok:
                groups.append("\n\n".join(current))
                current = [para]
                current_tok = para_tok
            else:
                current.append(para)
                current_tok += para_tok
        if current:
            groups.append("\n\n".join(current))

        chunks: list[dict[str, Any]] = []
        for idx, text in enumerate(groups):
            chunks.append(
                _make_chunk(
                    source_url=source_url,
                    source_type=source_type,
                    title=title,
                    content=f"{title}\n\n{text}",
                    chunk_index=idx,
                    video_id=video_id,
                    iq_layers=iq_layers,
                    azure_services=azure_services,
                    published_at=published_at,
                )
            )
        return _patch_total_chunks(chunks)


# ---------------------------------------------------------------------------
# AtomicChunker — Azure Updates RSS items
# ---------------------------------------------------------------------------


class AtomicChunker:
    """
    No-split chunker.  The entire document becomes a single chunk.
    Used for Azure Updates RSS items where each entry is already atomic.
    """

    def chunk(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Wrap the document as a single atomic chunk.

        Expected keys in *doc*:
            url, source_type, title, content,
            iq_layers, azure_services, published_at
        """
        source_url: str = doc.get("url", "")
        source_type: str = doc.get("source_type", SourceType.AZURE_UPDATE)
        title: str = doc.get("title", "")
        content: str = doc.get("content", "")
        iq_layers: list[str] = doc.get("iq_layers", [])
        azure_services: list[str] = doc.get("azure_services", [])
        published_at: str = doc.get("published_at", "")

        if not content.strip():
            logger.warning("AtomicChunker: empty content for %s", source_url)
            return []

        chunk = _make_chunk(
            source_url=source_url,
            source_type=str(source_type),
            title=title,
            content=content,
            heading_path="",
            chunk_index=0,
            total_chunks=1,
            iq_layers=iq_layers,
            azure_services=azure_services,
            published_at=published_at,
        )
        chunk["total_chunks"] = 1
        return [chunk]


# ---------------------------------------------------------------------------
# ContentTypeAwareChunker — main entry point
# ---------------------------------------------------------------------------

# Source types that route to DocumentChunker
_DOCUMENT_TYPES: frozenset[str] = frozenset(
    [
        SourceType.MS_LEARN,
        SourceType.TECH_COMMUNITY,
        SourceType.BLOG_POST,
        SourceType.ARCHITECTURE_PATTERN,
        SourceType.CODE_SAMPLE,
        # raw strings in case caller doesn't use the enum
        "ms-learn",
        "tech-community",
        "blog-post",
        "architecture",
        "code-sample",
    ]
)

_TRANSCRIPT_TYPES: frozenset[str] = frozenset(
    [
        SourceType.VIDEO_TRANSCRIPT,
        "video-transcript",
        "youtube",
        "transcript",
    ]
)

_ATOMIC_TYPES: frozenset[str] = frozenset(
    [
        SourceType.AZURE_UPDATE,
        "azure-update",
        "rss",
        "update",
    ]
)


class ContentTypeAwareChunker:
    """
    Main routing entry point for content-type-aware chunking (ADR-003).

    Usage::

        chunker = ContentTypeAwareChunker()
        chunks  = chunker.chunk(crawled_doc)

    *crawled_doc* must contain at minimum:
        - ``source_type``: one of the SourceType enum values (or a recognised alias)
        - ``url``: canonical URL of the document
        - ``title``: document title
        - ``content``: raw text / markdown

    Optional keys vary by strategy (see individual chunker docstrings).
    """

    def __init__(
        self,
        max_chunk_tokens: int = 512,
        overlap_tokens: int = 128,
        topic_gap_seconds: float = 30.0,
    ) -> None:
        config = ChunkConfig(
            max_chunk_tokens=max_chunk_tokens,
            overlap_tokens=overlap_tokens,
            topic_gap_seconds=topic_gap_seconds,
        )
        self._doc_chunker = DocumentChunker(config)
        self._tx_chunker = TranscriptChunker(config)
        self._atomic_chunker = AtomicChunker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Chunk *doc* using the strategy appropriate for its ``source_type``.

        Returns a list of chunk dicts in the standard format defined in ADR-003.
        Raises ``ValueError`` for unrecognised source types.
        """
        raw_type = doc.get("source_type", "")

        # Normalise via enum if possible
        try:
            source_type_enum = SourceType(raw_type)
            normalised: str = source_type_enum.value
        except ValueError:
            normalised = str(raw_type).lower().strip()

        logger.debug(
            "ContentTypeAwareChunker: routing '%s' → strategy for '%s'",
            doc.get("url", "<no-url>"),
            normalised,
        )

        if normalised in _DOCUMENT_TYPES:
            return self._doc_chunker.chunk(doc)

        if normalised in _TRANSCRIPT_TYPES:
            return self._tx_chunker.chunk(doc)

        if normalised in _ATOMIC_TYPES:
            return self._atomic_chunker.chunk(doc)

        # Unknown type — log warning and attempt DocumentChunker as safe default
        logger.warning(
            "ContentTypeAwareChunker: unknown source_type '%s' for %s — "
            "falling back to DocumentChunker",
            raw_type,
            doc.get("url", "<no-url>"),
        )
        return self._doc_chunker.chunk(doc)

    def chunk_many(
        self, docs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Convenience method to chunk a list of documents in one call.
        Returns a flat list of all chunks across all documents.
        """
        all_chunks: list[dict[str, Any]] = []
        for doc in docs:
            try:
                all_chunks.extend(self.chunk(doc))
            except Exception:
                logger.exception(
                    "ContentTypeAwareChunker: failed to chunk %s",
                    doc.get("url", "<unknown>"),
                )
        return all_chunks
