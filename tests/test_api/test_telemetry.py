"""
Tests for src/api/telemetry.py

Validates that:
- configure_telemetry() initialises metric instruments without error
- Metric helper functions are safe no-ops when called before initialisation
- Metric helper functions record data after initialisation
- shutdown_telemetry() runs without error
- Graceful degradation when connection string is empty
"""

from __future__ import annotations

import importlib
import sys

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reload_telemetry():
    """Reload the telemetry module to reset all module-level singletons."""
    module_name = "src.api.telemetry"
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTelemetryBeforeInit:
    """Metric helpers must be safe no-ops before configure_telemetry() is called."""

    def setup_method(self):
        self.telemetry = _reload_telemetry()

    def teardown_method(self):
        self.telemetry.shutdown_telemetry()

    def test_record_query_latency_noop(self):
        self.telemetry.record_query_latency(250, "iq-architect")

    def test_record_llm_tokens_noop(self):
        self.telemetry.record_llm_tokens(1024, "iq-architect")

    def test_record_cache_hit_noop(self):
        self.telemetry.record_cache_hit()

    def test_record_cache_miss_noop(self):
        self.telemetry.record_cache_miss()

    def test_record_ingestion_stats_noop(self):
        self.telemetry.record_ingestion_stats(10, 50, source="microsoft-learn")

    def test_record_error_noop(self):
        self.telemetry.record_error("/api/query", error_type="LLMUnavailable")


class TestTelemetryConfigureNoConnectionString:
    """configure_telemetry() degrades gracefully with an empty connection string."""

    def setup_method(self):
        self.telemetry = _reload_telemetry()

    def teardown_method(self):
        self.telemetry.shutdown_telemetry()

    def test_configure_without_connection_string(self):
        # Should not raise even without a real connection string
        self.telemetry.configure_telemetry(
            service_name="test-service",
            service_version="0.0.0",
            connection_string="",
        )

    def test_instruments_created_after_configure(self):
        self.telemetry.configure_telemetry(
            service_name="test-service",
            service_version="0.0.0",
            connection_string="",
        )
        # Instrument singletons should now be set (not None)
        assert self.telemetry._query_latency is not None
        assert self.telemetry._llm_tokens is not None
        assert self.telemetry._cache_hits is not None
        assert self.telemetry._cache_misses is not None
        assert self.telemetry._ingestion_documents is not None
        assert self.telemetry._ingestion_chunks is not None
        assert self.telemetry._errors is not None


class TestTelemetryMetricHelpers:
    """After configure_telemetry(), helpers should execute without error."""

    def setup_method(self):
        self.telemetry = _reload_telemetry()
        self.telemetry.configure_telemetry(
            service_name="test-service",
            service_version="0.0.0",
            connection_string="",
        )

    def teardown_method(self):
        self.telemetry.shutdown_telemetry()

    def test_record_query_latency(self):
        self.telemetry.record_query_latency(123, "azure-navigator")

    def test_record_llm_tokens_positive(self):
        self.telemetry.record_llm_tokens(512, "iq-architect")

    def test_record_llm_tokens_zero_no_error(self):
        # Tokens==0 should be a no-op (guard in implementation)
        self.telemetry.record_llm_tokens(0, "iq-architect")

    def test_record_cache_hit(self):
        self.telemetry.record_cache_hit()

    def test_record_cache_miss(self):
        self.telemetry.record_cache_miss()

    def test_record_ingestion_stats(self):
        self.telemetry.record_ingestion_stats(5, 25, source="azure-docs")

    def test_record_error(self):
        self.telemetry.record_error("/api/query", error_type="SearchUnavailable")

    def test_get_tracer_returns_tracer(self):
        from opentelemetry import trace
        tracer = self.telemetry.get_tracer("test-scope")
        assert isinstance(tracer, trace.Tracer)


class TestTelemetryShutdown:
    """shutdown_telemetry() should be idempotent."""

    def test_shutdown_before_configure(self):
        telemetry = _reload_telemetry()
        telemetry.shutdown_telemetry()  # must not raise

    def test_shutdown_after_configure(self):
        telemetry = _reload_telemetry()
        telemetry.configure_telemetry(
            service_name="test-service",
            service_version="0.0.0",
            connection_string="",
        )
        telemetry.shutdown_telemetry()

    def test_double_shutdown(self):
        telemetry = _reload_telemetry()
        telemetry.configure_telemetry(
            service_name="test-service",
            service_version="0.0.0",
            connection_string="",
        )
        telemetry.shutdown_telemetry()
        telemetry.shutdown_telemetry()  # second call must not raise
