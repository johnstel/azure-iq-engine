"""
Tests for the keyword-based query router used by the engine (src/api/router_query.py).

These tests focus on routing correctness and edge cases.
"""

from __future__ import annotations

import pytest

from src.api.router_query import (
    DEFAULT_AGENT,
    ROUTING_RULES,
    RoutingRule,
    _valid_agents,
    list_agents,
    route_question,
)


# ── Keyword matching ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("question,expected_agent", [
    # latest-updates
    ("What changed in Fabric this week?", "latest-updates"),
    ("Any new feature announcements?", "latest-updates"),
    ("Is this GA or preview?", "latest-updates"),
    ("Azure OpenAI has been deprecated", "latest-updates"),
    # competitive-context
    ("Azure versus AWS for data workloads", "competitive-context"),
    ("How does Fabric compare to Databricks?", "competitive-context"),
    ("Tell me about Snowflake alternatives", "competitive-context"),
    # customer-researcher
    ("Research Contoso customer profile", "customer-researcher"),
    ("Create an outcome doc for this opportunity", "customer-researcher"),
    # azure-navigator
    ("How do I configure Azure Synapse?", "azure-navigator"),
    ("What is the pricing for Azure Data Factory?", "azure-navigator"),
    ("Best practice for deploying an AKS cluster", "azure-navigator"),
    # iq-architect
    ("Explain the Work IQ architecture", "iq-architect"),
    ("What design patterns apply to Fabric IQ?", "iq-architect"),
    ("Show me a medallion lakehouse reference architecture", "iq-architect"),
])
def test_route_question_keyword_matching(question, expected_agent):
    assert route_question(question) == expected_agent


def test_route_question_empty_string_returns_default():
    assert route_question("") == DEFAULT_AGENT


def test_route_question_whitespace_returns_default():
    assert route_question("   ") == DEFAULT_AGENT


def test_route_question_preferred_agent_must_be_valid():
    """A valid preferred_agent bypasses keyword routing."""
    for agent_name in _valid_agents():
        result = route_question("Any question", preferred_agent=agent_name)
        assert result == agent_name


def test_route_question_invalid_preferred_agent_triggers_auto_route():
    result = route_question("What changed this week?", preferred_agent="fake-agent")
    assert result == "latest-updates"


# ── ROUTING_RULES integrity ───────────────────────────────────────────────────

def test_all_rules_have_agent_name():
    for rule in ROUTING_RULES:
        assert rule.agent.strip() != ""


def test_all_rules_have_at_least_one_keyword():
    for rule in ROUTING_RULES:
        assert len(rule.keywords) > 0


def test_all_rules_have_description():
    for rule in ROUTING_RULES:
        assert rule.description.strip() != ""


def test_default_agent_is_in_valid_agents():
    assert DEFAULT_AGENT in _valid_agents()


# ── list_agents ───────────────────────────────────────────────────────────────

def test_list_agents_includes_all_routing_rule_agents():
    agent_names = {a["name"] for a in list_agents()}
    for rule in ROUTING_RULES:
        assert rule.agent in agent_names, f"{rule.agent} missing from list_agents()"


def test_list_agents_no_duplicates():
    names = [a["name"] for a in list_agents()]
    assert len(names) == len(set(names))


def test_list_agents_each_has_description():
    for agent in list_agents():
        assert "description" in agent
        assert agent["description"].strip() != ""
