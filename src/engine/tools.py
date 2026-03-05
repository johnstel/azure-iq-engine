"""
Function tools for IQ Engine agents.

These are registered with Agent Framework agents via the `tools` parameter.
Each tool is a typed function that the LLM can invoke during reasoning.
"""


async def search_iq_corpus(
    query: str,
    iq_layers: list[str] | None = None,
    azure_services: list[str] | None = None,
    source_types: list[str] | None = None,
    target_role: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Search the IQ knowledge corpus using hybrid vector + BM25 search
    with semantic reranking and scoring profiles.

    Args:
        query: Natural language search query
        iq_layers: Filter by IQ layer(s) — "work-iq", "fabric-iq", "foundry-iq"
        azure_services: Filter by Azure service(s)
        source_types: Filter by source — "ms-learn", "video-transcript", "azure-update", etc.
        target_role: Filter by audience role — "business-leader", "developer", etc.
        max_results: Number of results to return
    """
    # TODO: Implement Azure AI Search hybrid query with scoring profile
    raise NotImplementedError("search_iq_corpus — implement in Phase 1")


async def get_service_details(service_name: str) -> dict:
    """
    Get detailed information about a specific Azure service,
    including pricing, SLAs, regions, and Well-Architected guidance.
    """
    # TODO: Implement service detail lookup
    raise NotImplementedError("get_service_details — implement in Phase 2")


async def get_latest_updates(
    days: int = 7,
    iq_layers: list[str] | None = None,
) -> list[dict]:
    """
    Get the latest Azure updates and IQ-related announcements.
    Filtered to recent content from azure-update source type.
    """
    # TODO: Implement filtered search for recent updates
    raise NotImplementedError("get_latest_updates — implement in Phase 2")


async def bing_web_search(
    query: str,
    market: str = "en-US",
    count: int = 5,
) -> list[dict]:
    """
    Search the web via Bing API for customer research,
    competitive analysis, and current events.
    """
    # TODO: Implement Bing Web Search API call
    raise NotImplementedError("bing_web_search — implement in Phase 3")


async def generate_outcome_doc(
    customer_name: str,
    industry: str,
    research_data: dict,
    iq_recommendations: dict,
) -> str:
    """
    Generate a customer outcome document using the v3.0 template.
    Includes executive summary, IQ opportunity map, TCO/ROI,
    risk analysis, competitive context, and implementation roadmap.
    """
    # TODO: Implement outcome document generator
    raise NotImplementedError("generate_outcome_doc — implement in Phase 3")
