"""
API Settings — Pydantic v2 Settings with environment variable binding.

All Azure credentials and endpoints are sourced from environment variables.
Never hard-code credentials; use Azure Key Vault in production.
"""

from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ─────────────────────────────────────────────────────────────────
    app_name: str = "Azure IQ Engine"
    app_version: str = "0.3.0"
    app_description: str = (
        "Grounded AI Q&A over the Microsoft IQ layer stack — "
        "Work IQ, Fabric IQ, and Foundry IQ — powered by Azure AI Foundry "
        "and Azure AI Search."
    )
    debug: bool = False

    # ── Azure AI Foundry / OpenAI ────────────────────────────────────────────
    foundry_base_url: str = Field(
        default="",
        description="Azure AI Foundry project endpoint (FOUNDRY_BASE_URL)",
    )
    foundry_key: str = Field(
        default="",
        description="Azure AI Foundry API key (FOUNDRY_KEY)",
    )
    openai_deployment: str = Field(
        default="Kimi-K2.5",
        description="Chat completion deployment name on Azure AI Foundry",
    )
    openai_embedding_deployment: str = Field(
        default="text-embedding-3-large",
        description="Embedding deployment name",
    )

    # ── Azure AI Search ──────────────────────────────────────────────────────
    search_endpoint: str = Field(
        default="",
        description="Azure AI Search endpoint (SEARCH_ENDPOINT)",
    )
    search_api_key: str = Field(
        default="",
        description="Azure AI Search admin key (SEARCH_API_KEY)",
    )
    search_index_name: str = Field(
        default="iq-engine-index",
        description="Name of the primary search index",
    )
    search_top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Default number of search results to retrieve for RAG",
    )

    # ── Grounding with Bing Search ──────────────────────────────────────────
    bing_grounding_connection_id: str = Field(
        default="",
        description=(
            "Grounding with Bing Search connection ID for Azure AI Foundry "
            "(BING_GROUNDING_CONNECTION_ID). Format: "
            "/subscriptions/{sub}/resourceGroups/{rg}/providers/"
            "Microsoft.CognitiveServices/accounts/{account}/"
            "connections/{connection-name}"
        ),
    )
    bing_grounding_endpoint: str = Field(
        default="",
        description=(
            "Grounding with Bing Search resource endpoint "
            "(BING_GROUNDING_ENDPOINT). e.g. https://api.bing.microsoft.com/v7.0"
        ),
    )
    bing_grounding_key: str = Field(
        default="",
        description="Grounding with Bing Search API key (BING_GROUNDING_KEY)",
    )

    # ── Rate limiting ────────────────────────────────────────────────────────
    rate_limit_query_rpm: int = Field(
        default=30,
        description="Max /api/query requests per minute per IP",
    )
    rate_limit_research_rpm: int = Field(
        default=10,
        description="Max /api/research requests per minute per IP",
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins (restrict in production)",
    )

    # ── IQ Layers ────────────────────────────────────────────────────────────
    iq_layers: list[str] = Field(
        default=["work-iq", "fabric-iq", "foundry-iq"],
        description="Recognised IQ layer identifiers",
    )

    # ── Redis Cache ──────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="",
        description=(
            "Redis connection URL for query caching (REDIS_URL). "
            "Example: redis://localhost:6379/0 "
            "Leave empty to disable caching."
        ),
    )

    # ── Azure Application Insights / OpenTelemetry ───────────────────────────
    applicationinsights_connection_string: str = Field(
        default="",
        description=(
            "Azure Application Insights connection string "
            "(APPLICATIONINSIGHTS_CONNECTION_STRING). "
            "Leave empty to disable telemetry."
        ),
    )

    # ── Admin ────────────────────────────────────────────────────────────────
    admin_api_key: str = Field(
        default="",
        description=(
            "Optional static API key protecting admin endpoints such as "
            "POST /api/cache/invalidate (ADMIN_API_KEY). "
            "Leave empty to allow unauthenticated access (dev only)."
        ),
    )

    # ── Content sources ──────────────────────────────────────────────────────
    content_sources: list[str] = Field(
        default=[
            "microsoft-learn",
            "azure-docs",
            "azure-updates",
            "techcommunity",
            "azure411-blog",
        ],
        description="Recognised content source identifiers",
    )

    @field_validator("foundry_base_url", "search_endpoint", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if v else v

    @property
    def has_foundry(self) -> bool:
        return bool(self.foundry_base_url and self.foundry_key)

    @property
    def has_search(self) -> bool:
        return bool(self.search_endpoint and self.search_api_key)

    @property
    def has_bing(self) -> bool:
        return bool(self.bing_grounding_key and self.bing_grounding_endpoint)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — safe to import anywhere."""
    return Settings()
