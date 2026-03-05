"""
Azure OpenAI client via Foundry + Microsoft Agent Framework (ADR-001).

Replaces Copilot SDK — Agent Framework is the server-native agent runtime
for building multi-agent systems on Azure AI Foundry.

Key packages:
  pip install agent-framework --pre
  pip install agent-framework-azure-ai
"""

import os
from azure.identity import DefaultAzureCredential


def get_foundry_client():
    """
    Create an Azure OpenAI Responses client via Foundry endpoint.
    Uses DefaultAzureCredential (managed identity in prod, Azure CLI in dev).
    """
    # agent_framework.azure requires agent-framework-azure-ai package
    from agent_framework.azure import AzureOpenAIResponsesClient

    return AzureOpenAIResponsesClient(
        credential=DefaultAzureCredential(),
        endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    )


def get_embedding_client():
    """
    Create an Azure OpenAI client for embedding generation.
    Uses text-embedding-3-large (1536-dim).
    """
    from openai import AsyncAzureOpenAI

    return AsyncAzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_ad_token_provider=DefaultAzureCredential(),
        api_version="2024-06-01",
    )
