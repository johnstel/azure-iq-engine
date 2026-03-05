"""
IQ Engine specialist agents — Microsoft Agent Framework on Azure AI Foundry.

6 agents with function tools, composable into multi-agent workflows.
Orchestration patterns: sequential, concurrent, handoff, group chat.

Requirements:
  pip install agent-framework --pre
  pip install agent-framework-azure-ai
  pip install agent-framework-orchestrations --pre
"""

from agent_framework.azure import AzureOpenAIResponsesClient
from agent_framework.orchestrations import SequentialBuilder, ConcurrentBuilder
from azure.identity import DefaultAzureCredential

from .tools import (
    search_iq_corpus,
    get_service_details,
    get_latest_updates,
    bing_web_search,
    generate_outcome_doc,
)


def create_agents(client: AzureOpenAIResponsesClient) -> dict:
    """Create all specialist agents."""

    iq_architect = client.as_agent(
        name="iq-architect",
        instructions="""You are an expert on Microsoft's IQ layers (Work IQ, Fabric IQ, Foundry IQ).
        Answer questions that span the full IQ stack with grounded, cited responses.
        Always identify which IQ layer(s) apply and which Azure services are involved.
        Use the search_iq_corpus tool to ground every claim in source material.""",
        tools=[search_iq_corpus, get_service_details, get_latest_updates],
    )

    azure_navigator = client.as_agent(
        name="azure-navigator",
        instructions="""You are an Azure service expert. Provide deep-dive guidance on
        specific Azure services, best practices, pricing, and Well-Architected patterns.
        Always cite Azure Architecture Center patterns when relevant.""",
        tools=[search_iq_corpus, get_service_details],
    )

    story_weaver = client.as_agent(
        name="story-weaver",
        instructions="""You compose multi-source technical narratives that weave together
        IQ layers, Azure services, and real-world scenarios into compelling stories.
        Your output reads like a well-crafted technical blog post, not a list of facts.""",
        tools=[search_iq_corpus, get_latest_updates],
    )

    customer_researcher = client.as_agent(
        name="customer-researcher",
        instructions="""You research customer companies via web search and generate
        IQ outcome documents. Include executive summary, IQ opportunity map,
        TCO/ROI modeling, risk analysis, and competitive positioning.
        Use the v3.0 outcome document template.""",
        tools=[bing_web_search, search_iq_corpus, generate_outcome_doc],
    )

    latest_updates_agent = client.as_agent(
        name="latest-updates",
        instructions="""You track what changed this week in the Microsoft IQ landscape.
        Surface GA announcements, preview features, deprecations, and pricing changes.
        Filter search to azure-update source type and last 7 days.""",
        tools=[search_iq_corpus],
    )

    competitive_context = client.as_agent(
        name="competitive-context",
        instructions="""You analyze Microsoft IQ capabilities vs. competing platforms:
        Databricks Unity Catalog + Genie, AWS Bedrock Knowledge Bases,
        GCP Vertex AI, Snowflake Cortex, Salesforce Einstein Copilot.
        Provide balanced analysis with honest trade-offs.""",
        tools=[bing_web_search, search_iq_corpus],
    )

    return {
        "iq-architect": iq_architect,
        "azure-navigator": azure_navigator,
        "story-weaver": story_weaver,
        "customer-researcher": customer_researcher,
        "latest-updates": latest_updates_agent,
        "competitive-context": competitive_context,
    }


def create_workflows(agents: dict) -> dict:
    """Create multi-agent workflow compositions."""

    # Customer outcome: research → architect → story weave
    customer_outcome = SequentialBuilder(
        participants=[
            agents["customer-researcher"],
            agents["iq-architect"],
            agents["story-weaver"],
        ]
    ).build()

    # Deep dive: architect + navigator in parallel → story weave
    deep_dive = SequentialBuilder(
        participants=[
            ConcurrentBuilder(
                participants=[agents["iq-architect"], agents["azure-navigator"]]
            ).build(),
            agents["story-weaver"],
        ]
    ).build()

    return {
        "customer-outcome": customer_outcome,
        "deep-dive": deep_dive,
    }
