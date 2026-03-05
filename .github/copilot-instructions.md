# Copilot Coding Agent Instructions

## Project Overview
Azure IQ Engine — a Python knowledge application unifying Microsoft's IQ layers (Work IQ, Fabric IQ, Foundry IQ) with Azure services. Built on FastAPI + Microsoft Agent Framework + Azure AI Search.

## Tech Stack
- **Python 3.12+** — type hints, async/await, dataclasses throughout
- **FastAPI** — async web framework with Pydantic v2 models
- **Microsoft Agent Framework** (RC) — multi-agent orchestration
- **Azure AI Search** — vector + semantic hybrid search
- **Azure OpenAI** via AI Foundry — chat (gpt-5.1-codex) + embeddings (text-embedding-3-large)
- **Azure Table Storage** — ingestion state, fingerprints
- **httpx** — async HTTP client (preferred over requests/aiohttp)
- **tiktoken** — token counting (cl100k_base encoding)
- **pytest + pytest-asyncio** — testing

## Code Style
- Python 3.12+ syntax (type unions with `|`, match statements OK)
- All functions must have type hints (params + return)
- Use `dataclasses` for data structures, `Pydantic v2 BaseModel` for API schemas
- Use `logging` module (not print statements)
- Async by default for I/O operations
- Max line length: 120 characters
- Use `ruff` for linting

## Architecture
```
src/
├── api/           # FastAPI endpoints, models, middleware
├── engine/        # Agent Framework agents, tools, workflows
├── ingestion/     # Crawlers, chunker, embedder, indexer, orchestrator
│   └── crawlers/  # Source-specific crawlers
└── static/        # Web UI (vanilla HTML/JS)
infra/             # Terraform for Azure resources
tests/             # pytest test suite
```

## Key Patterns
- **Graceful degradation**: If an Azure service isn't configured (missing env var), log a warning and return a stub/empty response. Never crash.
- **Checkpoint/resume**: All crawlers save progress as JSON files. Interrupted runs resume from last checkpoint.
- **SHA256 fingerprinting**: Content deduplication via `hashlib.sha256(url + content)`.
- **Batch processing**: Azure OpenAI embeddings (batch 16), AI Search indexing (batch 500).
- **Rate limiting**: Semaphores for concurrent API calls, exponential backoff on 429s.

## Environment Variables
- `FOUNDRY_BASE_URL` — Azure AI Foundry endpoint
- `FOUNDRY_KEY` — Foundry API key
- `SEARCH_ENDPOINT` — Azure AI Search endpoint
- `SEARCH_API_KEY` — AI Search admin key
- `BING_API_KEY` — Bing Search API (optional)
- `YOUTUBE_API_KEY` — YouTube Data API (optional)
- `REDIS_URL` — Redis connection (optional)

## Testing
- Mock all external Azure services (no real API calls in tests)
- Use `pytest-asyncio` for async tests
- Fixtures in `tests/conftest.py`
- Test files mirror source structure: `tests/test_api/`, `tests/test_ingestion/`, `tests/test_engine/`

## PR Requirements
- All Python files must pass `python -m py_compile`
- All existing tests must pass
- New code should include tests where practical
- Update CHANGELOG.md for user-facing changes
