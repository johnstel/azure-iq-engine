"""
Keyword-based query router for MVP agent selection.

Maps incoming question text to the most appropriate specialist agent.
In production, replace with a lightweight embedding classifier or
let the orchestrator agent self-route via tool calls.

Agent registry mirrors engine/agents.py:
  iq-architect         — IQ layer stack, architecture, design patterns
  azure-navigator      — Azure services, resources, how-to guidance
  latest-updates       — Recent announcements, GA events, deprecations
  competitive-context  — Competitor comparisons, market positioning
  story-weaver         — Narrative synthesis, multi-source docs
  customer-researcher  — Customer/company research, outcome docs
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Routing table ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingRule:
    agent: str
    keywords: tuple[str, ...]
    description: str


ROUTING_RULES: list[RoutingRule] = [
    RoutingRule(
        agent="latest-updates",
        keywords=(
            "what changed", "what's new", "update", "updates", "updated",
            "new feature", "new features", "announce", "announced", "announcement",
            "ga ", "generally available", "preview", "deprecat", "retire",
            "release", "changelog", "this week", "this month",
        ),
        description="Tracks recent Microsoft IQ / Azure announcements",
    ),
    RoutingRule(
        agent="competitive-context",
        keywords=(
            " vs ", " vs.", "versus", "compare", "comparison", "competitor",
            "databricks", "aws", "amazon", "gcp", "google cloud",
            "snowflake", "salesforce", "einstein", "openai", "bedrock",
            "vertex ai", "cortex", "market position", "alternative",
        ),
        description="Competitive analysis and market positioning",
    ),
    RoutingRule(
        agent="customer-researcher",
        keywords=(
            "customer", "client", "company", "prospect", "account",
            "research ", "profile", "outcome doc", "pitch",
            "opportunity", "engagement", "use case for",
        ),
        description="Customer/company research and outcome documents",
    ),
    RoutingRule(
        agent="azure-navigator",
        keywords=(
            "service", "resource", "resources", "how to", "how do i",
            "configure", "setup", "set up", "deploy", "pricing", "cost",
            "well-architected", "best practice", "sku", "tier",
            "quota", "limit", "region", "availability zone",
        ),
        description="Azure service deep-dives and how-to guidance",
    ),
    RoutingRule(
        agent="iq-architect",
        keywords=(
            "architecture", "architect", "design", "pattern", "patterns",
            "work iq", "fabric iq", "foundry iq", "iq layer", "iq stack",
            "integration", "solution", "reference architecture",
            "medallion", "lakehouse", "copilot stack",
        ),
        description="IQ layer architecture and design patterns",
    ),
]

DEFAULT_AGENT = "iq-architect"

# Agents that exist in the engine but have no dedicated keyword routing.
# They can still be explicitly requested via preferred_agent.
SUPPLEMENTAL_AGENTS: dict[str, str] = {
    "story-weaver": "Narrative synthesis across IQ layers and Azure services",
    "customer-researcher": "Customer/company research and outcome documents",
}

# ── Public API ────────────────────────────────────────────────────────────────

def route_question(question: str, preferred_agent: str | None = None) -> str:
    """
    Return the agent name that should handle *question*.

    Args:
        question: The user's natural-language question.
        preferred_agent: If provided and valid, returns it immediately.

    Returns:
        An agent name string.
    """
    if preferred_agent and preferred_agent in _valid_agents():
        return preferred_agent

    normalised = question.lower()

    for rule in ROUTING_RULES:
        for kw in rule.keywords:
            if kw in normalised:
                return rule.agent

    return DEFAULT_AGENT


def _valid_agents() -> set[str]:
    return (
        {rule.agent for rule in ROUTING_RULES}
        | {DEFAULT_AGENT}
        | set(SUPPLEMENTAL_AGENTS)
    )


def list_agents() -> list[dict]:
    """Return metadata for all registered agents (for /info endpoint)."""
    seen: dict[str, str] = {}
    for rule in ROUTING_RULES:
        seen.setdefault(rule.agent, rule.description)
    seen.setdefault(DEFAULT_AGENT, "IQ layer architecture (default)")
    for name, desc in SUPPLEMENTAL_AGENTS.items():
        seen.setdefault(name, desc)
    return [{"name": k, "description": v} for k, v in seen.items()]
