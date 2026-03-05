"""
Azure IQ Engine — OpenTelemetry + Azure Application Insights Telemetry

Provides:
  - Distributed tracing via TracerProvider
  - Custom metrics via MeterProvider
  - Azure Monitor (Application Insights) exporter when
    APPLICATIONINSIGHTS_CONNECTION_STRING is set

Graceful degradation: if the connection string is absent or packages are
missing, all calls become no-ops using the default OpenTelemetry SDK no-op
implementations.

Usage
-----
    from .telemetry import init_telemetry, get_tracer, get_meter
    from .telemetry import metrics   # pre-built instrument wrappers

Instrument names
----------------
    iq_engine.query.duration    — histogram (ms)
    iq_engine.query.tokens      — counter
    iq_engine.cache.hits        — counter
    iq_engine.cache.misses      — counter
    iq_engine.ingestion.chunks  — counter
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_initialised: bool = False


# ---------------------------------------------------------------------------
# No-op shims — used when OpenTelemetry SDK is unavailable
# ---------------------------------------------------------------------------

class _NoOpHistogram:
    def record(self, value: float, attributes: dict | None = None) -> None:  # noqa: D401
        pass


class _NoOpCounter:
    def add(self, amount: int | float, attributes: dict | None = None) -> None:  # noqa: D401
        pass


class _NoOpSpan:
    def set_attribute(self, key: str, value: object) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    def start_as_current_span(self, name: str, **kwargs) -> _NoOpSpan:
        return _NoOpSpan()

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs) -> Generator[_NoOpSpan, None, None]:  # type: ignore[misc]
        yield _NoOpSpan()


# ---------------------------------------------------------------------------
# Metric instrument container
# ---------------------------------------------------------------------------

@dataclass
class _Metrics:
    query_duration: object = field(default_factory=_NoOpHistogram)
    query_tokens: object = field(default_factory=_NoOpCounter)
    cache_hits: object = field(default_factory=_NoOpCounter)
    cache_misses: object = field(default_factory=_NoOpCounter)
    ingestion_chunks: object = field(default_factory=_NoOpCounter)


metrics = _Metrics()
_tracer: object = _NoOpTracer()


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------

def get_tracer() -> object:
    """Return the active tracer (real or no-op)."""
    return _tracer


def get_metrics() -> _Metrics:
    """Return the metric instrument container."""
    return metrics


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_telemetry(connection_string: str | None = None) -> None:
    """
    Bootstrap OpenTelemetry providers with the Azure Monitor exporter.

    Safe to call multiple times — subsequent calls are no-ops.

    Parameters
    ----------
    connection_string:
        Application Insights connection string.  When *None* or empty the
        function installs no-op providers and logs a warning.
    """
    global _initialised, _tracer, metrics

    if _initialised:
        return
    _initialised = True

    if not connection_string:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING not configured — "
            "telemetry is a no-op. Set the env var to enable Application Insights."
        )
        return

    # ── Try to import required packages ────────────────────────────────────
    try:
        from opentelemetry import metrics as otel_metrics, trace  # type: ignore[import]
        from opentelemetry.sdk.metrics import MeterProvider  # type: ignore[import]
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # type: ignore[import]
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME  # type: ignore[import]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import]
    except ImportError as exc:
        logger.warning(
            "OpenTelemetry SDK not installed (%s) — telemetry disabled. "
            "Install with: pip install opentelemetry-sdk",
            exc,
        )
        return

    try:
        from azure.monitor.opentelemetry.exporter import (  # type: ignore[import]
            AzureMonitorMetricExporter,
            AzureMonitorTraceExporter,
        )
    except ImportError as exc:
        logger.warning(
            "azure-monitor-opentelemetry-exporter not installed (%s) — "
            "telemetry disabled. "
            "Install with: pip install azure-monitor-opentelemetry-exporter",
            exc,
        )
        return

    # ── Shared resource ────────────────────────────────────────────────────
    resource = Resource(attributes={SERVICE_NAME: "azure-iq-engine"})

    # ── Tracing ────────────────────────────────────────────────────────────
    try:
        trace_exporter = AzureMonitorTraceExporter(connection_string=connection_string)
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
        trace.set_tracer_provider(tracer_provider)
        _tracer = trace.get_tracer("iq_engine")
        logger.info("OpenTelemetry tracing initialised → Application Insights")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tracing initialisation failed: %s", exc, exc_info=True)

    # ── Metrics ────────────────────────────────────────────────────────────
    try:
        metric_exporter = AzureMonitorMetricExporter(connection_string=connection_string)
        reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60_000)
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        otel_metrics.set_meter_provider(meter_provider)
        meter = otel_metrics.get_meter("iq_engine")

        metrics.query_duration = meter.create_histogram(
            name="iq_engine.query.duration",
            unit="ms",
            description="End-to-end query latency in milliseconds",
        )
        metrics.query_tokens = meter.create_counter(
            name="iq_engine.query.tokens",
            unit="tokens",
            description="Total LLM tokens consumed by query/research endpoints",
        )
        metrics.cache_hits = meter.create_counter(
            name="iq_engine.cache.hits",
            description="Number of Redis cache hits",
        )
        metrics.cache_misses = meter.create_counter(
            name="iq_engine.cache.misses",
            description="Number of Redis cache misses",
        )
        metrics.ingestion_chunks = meter.create_counter(
            name="iq_engine.ingestion.chunks",
            description="Number of document chunks indexed during ingestion runs",
        )
        logger.info("OpenTelemetry metrics initialised → Application Insights")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Metrics initialisation failed: %s", exc, exc_info=True)
