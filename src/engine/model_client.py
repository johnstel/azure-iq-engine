"""
ModelClient abstraction layer (ADR-001).

Copilot SDK provides chat/completion only — no embedding API.
Azure OpenAI is required for embeddings and serves as chat fallback.
ResilientModelRouter wraps both with circuit breaker pattern.
"""

from abc import ABC, abstractmethod
from typing import Protocol


class ModelClient(Protocol):
    """Interface for LLM providers."""

    async def chat(self, messages: list[dict], model: str = "gpt-5") -> str:
        """Send chat completion request."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...


class CopilotModelClient:
    """
    Primary chat provider — $0/token via GitHub license.
    Does NOT support embeddings (embed() raises NotImplementedError).
    """

    def __init__(self):
        # TODO: Initialize CopilotClient from github-copilot-sdk
        pass

    async def chat(self, messages: list[dict], model: str = "gpt-5") -> str:
        raise NotImplementedError("CopilotModelClient.chat — implement in Phase 2")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Copilot SDK does not support embeddings. Use AzureOpenAIModelClient."
        )


class AzureOpenAIModelClient:
    """
    Required for embeddings. Fallback for chat when Copilot SDK is down.
    Uses text-embedding-3-large (1536-dim).
    """

    def __init__(self, endpoint: str, api_key: str, api_version: str = "2024-06-01"):
        self.endpoint = endpoint
        self.api_key = api_key
        self.api_version = api_version
        # TODO: Initialize AsyncAzureOpenAI client

    async def chat(self, messages: list[dict], model: str = "gpt-5") -> str:
        raise NotImplementedError("AzureOpenAIModelClient.chat — implement in Phase 2")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("AzureOpenAIModelClient.embed — implement in Phase 1")


class ResilientModelRouter:
    """
    Circuit breaker wrapping both providers.
    
    Chat: Copilot SDK (primary) → Azure OpenAI (fallback)
    Embeddings: Azure OpenAI (only option)
    
    Circuit opens after 3 failures in 60 seconds.
    Half-open probe every 30 seconds.
    """

    def __init__(
        self,
        copilot: CopilotModelClient,
        azure_openai: AzureOpenAIModelClient,
        max_failures: int = 3,
        failure_window_seconds: int = 60,
    ):
        self.copilot = copilot
        self.azure_openai = azure_openai
        self.max_failures = max_failures
        self.failure_window_seconds = failure_window_seconds
        # TODO: Implement circuit breaker state machine

    async def chat(self, messages: list[dict], model: str = "gpt-5") -> str:
        """Route chat to Copilot SDK; fall back to Azure OpenAI on circuit open."""
        raise NotImplementedError("ResilientModelRouter.chat — implement in Phase 2")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Always route to Azure OpenAI — Copilot SDK doesn't support embeddings."""
        return await self.azure_openai.embed(texts)
