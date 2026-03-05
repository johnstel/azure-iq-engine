"""
AI Search Index Manager (ADR-005).

Provisions the ``iq-engine-index`` on Azure AI Search using the
``azure-search-documents`` SDK.  The schema mirrors ``infra/search_index.tf``:

- 19 text / metadata fields (filterable, facetable, sortable as appropriate)
- 1 × 1536-dimension vector field (HNSW, cosine, text-embedding-3-large)
- Semantic configuration: title → content → keywords (azure_services /
  capabilities / iq_layers)

Run as a CLI command to bootstrap or update the index::

    python -m src.ingestion.index_manager

The operation is idempotent — re-running against an existing index performs
a no-op (index already exists) or updates the definition if the schema has
changed.

Required environment variables:
    SEARCH_ENDPOINT   — e.g. https://srch-iq-engine-dev.search.windows.net
    SEARCH_API_KEY    — admin key from the Azure portal
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceExistsError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    SearchableField,
    VectorSearch,
    VectorSearchAlgorithmMetric,
    VectorSearchProfile,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

INDEX_NAME = "iq-engine-index"
_VECTOR_DIMENSIONS = 1536
_HNSW_ALGORITHM_NAME = "iq-hnsw"
_VECTOR_PROFILE_NAME = "iq-hnsw-profile"
_SEMANTIC_CONFIG_NAME = "iq-semantic"


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class IndexManagerConfig:
    """Runtime configuration resolved from environment variables."""

    search_endpoint: str = field(
        default_factory=lambda: os.getenv("SEARCH_ENDPOINT", "")
    )
    search_api_key: str = field(
        default_factory=lambda: os.getenv("SEARCH_API_KEY", "")
    )
    index_name: str = INDEX_NAME

    def validate(self) -> None:
        """Raise :class:`RuntimeError` if required credentials are absent."""
        if not self.search_endpoint:
            raise RuntimeError(
                "SEARCH_ENDPOINT environment variable is not set. "
                "Example: https://srch-iq-engine-dev.search.windows.net"
            )
        if not self.search_api_key:
            raise RuntimeError(
                "SEARCH_API_KEY environment variable is not set."
            )


# ── Schema helpers ─────────────────────────────────────────────────────────────

def _build_fields() -> list[SearchField | SimpleField | SearchableField]:
    """Return the complete field list for ``iq-engine-index``."""
    return [
        # ── Key ─────────────────────────────────────────────────────────────
        SimpleField(
            name="chunk_id",
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
            sortable=True,
            facetable=False,
        ),
        # ── Source metadata ──────────────────────────────────────────────────
        SearchableField(
            name="source_type",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="source_url",
            type=SearchFieldDataType.String,
            filterable=True,
        ),
        SearchableField(
            name="title",
            type=SearchFieldDataType.String,
            sortable=True,
            analyzer_name="en.microsoft",
        ),
        SimpleField(
            name="published_at",
            type=SearchFieldDataType.DateTimeOffset,
            filterable=True,
            sortable=True,
        ),
        # ── Content ──────────────────────────────────────────────────────────
        SearchableField(
            name="content",
            type=SearchFieldDataType.String,
            analyzer_name="en.microsoft",
        ),
        # ── IQ classification layers ─────────────────────────────────────────
        SearchableField(
            name="iq_layers",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SearchableField(
            name="azure_services",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SearchableField(
            name="capabilities",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SearchableField(
            name="entities",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        # ── Video-specific ───────────────────────────────────────────────────
        SimpleField(
            name="video_id",
            type=SearchFieldDataType.String,
            filterable=True,
        ),
        SimpleField(
            name="video_timestamp",
            type=SearchFieldDataType.Int32,
            sortable=True,
        ),
        # ── Quality & governance ─────────────────────────────────────────────
        SimpleField(
            name="ga_status",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="fingerprint",
            type=SearchFieldDataType.String,
            filterable=True,
        ),
        SimpleField(
            name="quality_score",
            type=SearchFieldDataType.Double,
            filterable=True,
            sortable=True,
        ),
        # ── Audience targeting ───────────────────────────────────────────────
        SearchableField(
            name="target_roles",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="difficulty",
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
            facetable=True,
        ),
        SearchableField(
            name="certification_tags",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="learn_lab_url",
            type=SearchFieldDataType.String,
        ),
        # ── Embedding vector (text-embedding-3-large = 1536 dims) ────────────
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=_VECTOR_DIMENSIONS,
            vector_search_profile_name=_VECTOR_PROFILE_NAME,
        ),
    ]


def _build_vector_search() -> VectorSearch:
    """Return HNSW vector search configuration (cosine metric).

    Parameter rationale (from HNSW literature and Azure AI Search guidance):
      m=4            — bi-directional link count; low value favours memory over
                       recall; 4 is appropriate for sub-100 K doc corpora.
      ef_construction=400 — candidate pool size during index build; higher
                       value improves recall at the cost of ingestion speed.
      ef_search=500  — candidate pool size at query time; 500 gives high recall
                       for knowledge-base workloads where precision matters more
                       than tail latency.
      metric=cosine  — normalised dot-product; required for OpenAI embedding
                       vectors (text-embedding-3-large outputs unit-norm vectors).
    """
    return VectorSearch(
        profiles=[
            VectorSearchProfile(
                name=_VECTOR_PROFILE_NAME,
                algorithm_configuration_name=_HNSW_ALGORITHM_NAME,
            )
        ],
        algorithms=[
            HnswAlgorithmConfiguration(
                name=_HNSW_ALGORITHM_NAME,
                parameters=HnswParameters(
                    m=4,
                    ef_construction=400,
                    ef_search=500,
                    metric=VectorSearchAlgorithmMetric.COSINE,
                ),
            )
        ],
    )


def _build_semantic_search() -> SemanticSearch:
    """Return semantic configuration (title → content → keyword fields)."""
    return SemanticSearch(
        default_configuration_name=_SEMANTIC_CONFIG_NAME,
        configurations=[
            SemanticConfiguration(
                name=_SEMANTIC_CONFIG_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[
                        SemanticField(field_name="azure_services"),
                        SemanticField(field_name="capabilities"),
                        SemanticField(field_name="iq_layers"),
                    ],
                ),
            )
        ],
    )


def build_index(index_name: str = INDEX_NAME) -> SearchIndex:
    """
    Construct the :class:`~azure.search.documents.indexes.models.SearchIndex`
    object representing the full ``iq-engine-index`` schema.

    :param index_name: Override the index name (useful for testing).
    :returns: A fully-configured :class:`SearchIndex` ready to be created or
              updated via :meth:`SearchIndexClient.create_or_update_index`.
    """
    return SearchIndex(
        name=index_name,
        fields=_build_fields(),
        vector_search=_build_vector_search(),
        semantic_search=_build_semantic_search(),
    )


# ── IndexManager ───────────────────────────────────────────────────────────────

class IndexManager:
    """
    Provisions and manages the ``iq-engine-index`` on Azure AI Search.

    Usage::

        manager = IndexManager()
        manager.ensure_index()   # idempotent — creates or updates

    The :meth:`ensure_index` method calls
    :meth:`~azure.search.documents.indexes.SearchIndexClient.create_or_update_index`,
    which is a safe upsert: creating the index if it does not exist or updating
    the definition if the schema has changed.
    """

    def __init__(self, config: IndexManagerConfig | None = None) -> None:
        self._cfg = config or IndexManagerConfig()

    def ensure_index(self) -> None:
        """
        Create or update the search index idempotently.

        :raises RuntimeError: If ``SEARCH_ENDPOINT`` or ``SEARCH_API_KEY`` are
                              not configured.
        :raises ~azure.core.exceptions.HttpResponseError: On unexpected Azure
                              API errors.
        """
        self._cfg.validate()

        client = SearchIndexClient(
            endpoint=self._cfg.search_endpoint,
            credential=AzureKeyCredential(self._cfg.search_api_key),
        )
        index = build_index(self._cfg.index_name)

        try:
            result = client.create_or_update_index(index)
            logger.info(
                "Index '%s' provisioned successfully (%d fields).",
                result.name,
                len(result.fields or []),
            )
        except ResourceExistsError:
            # Should not normally occur with create_or_update, but guard anyway
            logger.info("Index '%s' already exists — no changes made.", self._cfg.index_name)

    def delete_index(self) -> None:
        """
        Delete the search index.  Intended for teardown / re-provisioning.

        :raises RuntimeError: If required credentials are absent.
        """
        self._cfg.validate()

        client = SearchIndexClient(
            endpoint=self._cfg.search_endpoint,
            credential=AzureKeyCredential(self._cfg.search_api_key),
        )
        client.delete_index(self._cfg.index_name)
        logger.info("Index '%s' deleted.", self._cfg.index_name)


# ── CLI entry-point ────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry-point for index provisioning.

    Usage::

        python -m src.ingestion.index_manager [--delete]

    Options:
        --delete   Delete the index instead of creating/updating it.
    """
    _setup_logging()
    args = argv if argv is not None else sys.argv[1:]

    manager = IndexManager()

    try:
        if "--delete" in args:
            logger.info("Deleting index '%s'…", manager._cfg.index_name)
            manager.delete_index()
        else:
            logger.info(
                "Provisioning index '%s' on %s…",
                manager._cfg.index_name,
                manager._cfg.search_endpoint or "(SEARCH_ENDPOINT not set)",
            )
            manager.ensure_index()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
