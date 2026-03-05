"""
Observability — OpenTelemetry + Azure Application Insights.

Sets up distributed tracing and custom metrics for the Azure IQ Engine:

  * Distributed tracing via OTLP → Azure Monitor exporter
  * Custom metrics:
      - iq_engine.query.latency_ms   (histogram)  — end-to-end query latency
      - iq_engine.llm.tokens_used    (counter)    — cumulative LLM token consumption
      - iq_engine.cache.hits / .misses (counters) — Redis cache hit/miss tracking
      - iq_engine.ingestion.documents (counter)   — documents processed per run
      - iq_engine.ingestion.chunks    (counter)   — chunks indexed per run
      - iq_engine.errors              (counter)   — errors by endpoint

Telemetry is initialised once at application startup (see main.py lifespan).
When APPLICATIONINSIGHTS_CONNECTION_STRING is absent the module degrades
gracefully — metrics are still tracked in-process via the OTel SDK but not
exported to Azure Monitor.
"""

from __future__ import annotations

import logging

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

# ── Module-level singletons ───────────────────────────────────────────────────

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None

# Custom metric instruments (created once; reused across requests)
_query_latency: metrics.Histogram | None = None
_llm_tokens: metrics.Counter | None = None
_cache_hits: metrics.Counter | None = None
_cache_misses: metrics.Counter | None = None
_ingestion_documents: metrics.Counter | None = None
_ingestion_chunks: metrics.Counter | None = None
_errors: metrics.Counter | None = None


def configure_telemetry(
    service_name: str,
    service_version: str,
    connection_string: str,
) -> None:
    """
    Initialise OpenTelemetry tracing and metrics for the application.

    Should be called once during application startup.  Degrades gracefully
    when *connection_string* is empty — the SDK still runs in-process.

    Args:
        service_name: Logical service name sent to Azure Monitor.
        service_version: Service version sent as a resource attribute.
        connection_string: Application Insights connection string.
    """
    global _tracer_provider, _meter_provider  # noqa: PLW0603
    global _query_latency, _llm_tokens, _cache_hits, _cache_misses  # noqa: PLW0603
    global _ingestion_documents, _ingestion_chunks, _errors  # noqa: PLW0603

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
        }
    )

    # ── Trace exporter ────────────────────────────────────────────────────────
    span_exporters: list = []
    metric_readers: list = []

    if connection_string:
        try:
            from azure.monitor.opentelemetry.exporter import (
                AzureMonitorMetricExporter,
                AzureMonitorTraceExporter,
            )

            span_exporters.append(
                AzureMonitorTraceExporter(connection_string=connection_string)
            )
            metric_readers.append(
                PeriodicExportingMetricReader(
                    AzureMonitorMetricExporter(connection_string=connection_string),
                    export_interval_millis=60_000,  # flush every 60 s
                )
            )
            logger.info(
                "Azure Monitor OpenTelemetry exporters configured (connection string present)"
            )
        except ImportError:
            logger.warning(
                "azure-monitor-opentelemetry-exporter not installed — "
                "telemetry will not be exported to Application Insights"
            )
    else:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING not set — "
            "telemetry will not be exported to Application Insights"
        )

    # ── Tracer provider ───────────────────────────────────────────────────────
    _tracer_provider = TracerProvider(resource=resource)
    for exporter in span_exporters:
        _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(_tracer_provider)

    # ── Meter provider ────────────────────────────────────────────────────────
    _meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(_meter_provider)

    # ── Instruments ───────────────────────────────────────────────────────────
    meter = metrics.get_meter("iq_engine", version=service_version)

    _query_latency = meter.create_histogram(
        name="iq_engine.query.latency_ms",
        description="End-to-end query latency in milliseconds",
        unit="ms",
    )
    _llm_tokens = meter.create_counter(
        name="iq_engine.llm.tokens_used",
        description="Cumulative LLM tokens consumed",
        unit="tokens",
    )
    _cache_hits = meter.create_counter(
        name="iq_engine.cache.hits",
        description="Number of Redis cache hits",
    )
    _cache_misses = meter.create_counter(
        name="iq_engine.cache.misses",
        description="Number of Redis cache misses",
    )
    _ingestion_documents = meter.create_counter(
        name="iq_engine.ingestion.documents",
        description="Number of documents processed in ingestion runs",
    )
    _ingestion_chunks = meter.create_counter(
        name="iq_engine.ingestion.chunks",
        description="Number of chunks indexed in ingestion runs",
    )
    _errors = meter.create_counter(
        name="iq_engine.errors",
        description="Number of errors by endpoint",
    )

    logger.info("OpenTelemetry tracing and metrics initialised for '%s'", service_name)


def shutdown_telemetry() -> None:
    """Flush and shut down all telemetry providers gracefully."""
    if _meter_provider is not None:
        _meter_provider.shutdown()
    if _tracer_provider is not None:
        _tracer_provider.shutdown()


# ── Metric helpers (safe no-ops when not initialised) ─────────────────────────

def record_query_latency(latency_ms: int, agent: str) -> None:
    """Record end-to-end query latency.

    Args:
        latency_ms: Latency in milliseconds.
        agent: Agent name used for the query (used as a metric dimension).
    """
    if _query_latency is not None:
        _query_latency.record(latency_ms, {"agent": agent})


def record_llm_tokens(tokens: int, agent: str) -> None:
    """Record LLM token usage for a single request.

    Args:
        tokens: Total tokens consumed (prompt + completion).
        agent: Agent name for the request.
    """
    if _llm_tokens is not None and tokens > 0:
        _llm_tokens.add(tokens, {"agent": agent})


def record_cache_hit() -> None:
    """Increment the cache-hit counter."""
    if _cache_hits is not None:
        _cache_hits.add(1)


def record_cache_miss() -> None:
    """Increment the cache-miss counter."""
    if _cache_misses is not None:
        _cache_misses.add(1)


def record_ingestion_stats(documents: int, chunks: int, source: str = "unknown") -> None:
    """Record ingestion pipeline statistics.

    Args:
        documents: Number of documents processed.
        chunks: Number of chunks indexed.
        source: Content source identifier.
    """
    if _ingestion_documents is not None:
        _ingestion_documents.add(documents, {"source": source})
    if _ingestion_chunks is not None:
        _ingestion_chunks.add(chunks, {"source": source})


def record_error(endpoint: str, error_type: str = "unknown") -> None:
    """Increment the error counter for a given endpoint.

    Args:
        endpoint: API endpoint path (e.g. '/api/query').
        error_type: Short error category string.
    """
    if _errors is not None:
        _errors.add(1, {"endpoint": endpoint, "error_type": error_type})


def get_tracer(name: str) -> trace.Tracer:
    """Return an OTel tracer for the given instrumentation scope.

    Safe to call before :func:`configure_telemetry` — returns the no-op tracer
    in that case.
    """
    return trace.get_tracer(name)
