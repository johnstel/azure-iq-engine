"""
Tests for the keyword-based query router (src/api/router_query.py) as used
by the API layer. Focuses on routing contract and list_agents() output.
For exhaustive keyword coverage see tests/test_engine/test_router_query.py.
"""

from __future__ import annotations

import pytest

from src.api.router_query import (
    DEFAULT_AGENT,
    ROUTING_RULES,
    list_agents,
    route_question,
)


# ── route_question ────────────────────────────────────────────────────────────

class TestRouteQuestion:
    def test_default_agent_for_unknown_query(self):
        assert route_question("Hello world") == DEFAULT_AGENT

    def test_latest_updates_keyword(self):
        assert route_question("What changed in Azure this week?") == "latest-updates"

    def test_latest_updates_announcement_keyword(self):
        assert route_question("Any new announcements for Fabric?") == "latest-updates"

    def test_competitive_context_vs_keyword(self):
        assert route_question("Azure vs AWS for analytics") == "competitive-context"

    def test_competitive_context_databricks(self):
        assert route_question("How does Fabric compare to Databricks?") == "competitive-context"

    def test_customer_researcher_keyword(self):
        assert route_question("Research Contoso customer profile") == "customer-researcher"

    def test_azure_navigator_how_to(self):
        assert route_question("How do I configure Azure Synapse?") == "azure-navigator"

    def test_azure_navigator_pricing(self):
        assert route_question("What is the pricing for Azure Data Factory?") == "azure-navigator"

    def test_iq_architect_architecture(self):
        assert route_question("Explain the IQ layer architecture") == "iq-architect"

    def test_iq_architect_fabric_iq_keyword(self):
        assert route_question("Tell me about Fabric IQ design patterns") == "iq-architect"

    def test_case_insensitive_routing(self):
        assert route_question("WHAT CHANGED LAST MONTH?") == "latest-updates"

    def test_preferred_agent_overrides_routing(self):
        # Even a question that would route to latest-updates should respect preferred_agent
        result = route_question(
            "What changed?", preferred_agent="azure-navigator"
        )
        assert result == "azure-navigator"

    def test_invalid_preferred_agent_ignored(self):
        """An unrecognised preferred_agent should be ignored; auto-routing applies."""
        result = route_question("What changed this week?", preferred_agent="nonexistent")
        assert result == "latest-updates"

    def test_empty_question_falls_back_to_default(self):
        assert route_question("") == DEFAULT_AGENT

    def test_all_routing_rules_have_keywords(self):
        for rule in ROUTING_RULES:
            assert len(rule.keywords) > 0, f"Rule for {rule.agent} has no keywords"


# ── list_agents ───────────────────────────────────────────────────────────────

class TestListAgents:
    def test_returns_list_of_dicts(self):
        agents = list_agents()
        assert isinstance(agents, list)
        assert all(isinstance(a, dict) for a in agents)

    def test_each_agent_has_name_and_description(self):
        for agent in list_agents():
            assert "name" in agent
            assert "description" in agent

    def test_default_agent_included(self):
        names = {a["name"] for a in list_agents()}
        assert DEFAULT_AGENT in names

    def test_no_duplicate_agent_names(self):
        names = [a["name"] for a in list_agents()]
        assert len(names) == len(set(names))
