# Issue: Python MCP Client Integration

**Milestone:** 5 — Embedded AI via Embabel & Chatbot Interface
**Priority:** High
**Depends on:** Issue 11 (provider abstraction), Issue 12 (Embabel agents)

## Summary

Implement the Python-side MCP client that connects to the Embabel agent server, discovers available tools, and provides the `EmbabelProvider` implementation for the AI provider abstraction layer.

## Background

The official MCP Python SDK (`mcp` on PyPI) provides `ClientSession` for connecting to MCP servers. Embabel exposes its agents as MCP tools over SSE (Server-Sent Events) at `http://localhost:8080/sse`. This issue bridges the two by implementing a robust client that handles connection management, tool discovery, invocation, and streaming.

## Acceptance Criteria

- [ ] Add `mcp` Python SDK as optional dependency:
  ```toml
  [project.optional-dependencies]
  embabel = ["mcp>=1.0"]
  ```
  Install with: `pip install docgen[embabel]`
- [ ] Implement `EmbabelClient` class:
  ```python
  class EmbabelClient:
      def __init__(self, url: str = "http://localhost:8080/sse"):
          ...

      async def connect(self) -> None:
          """Connect to Embabel SSE endpoint."""

      async def discover_tools(self) -> list[Tool]:
          """List available MCP tools from Embabel."""

      async def invoke(self, tool_name: str, args: dict) -> Any:
          """Invoke an MCP tool and return the result."""

      async def stream(self, tool_name: str, args: dict) -> AsyncIterator[str]:
          """Invoke a tool with streaming response."""

      async def close(self) -> None:
          """Disconnect from Embabel."""
  ```
- [ ] Auto-reconnect on connection loss (exponential backoff, max 3 retries)
- [ ] Graceful degradation: if Embabel is unavailable, fall back to direct OpenAI provider
- [ ] Tool invocation wrappers for each agent tool:
  ```python
  async def generate_narration(self, segment: str, guidance: str, sources: list[str]) -> str:
      return await self.invoke("generate_narration", {...})
  ```
- [ ] Handle streaming responses for chat interactions (SSE event stream)
- [ ] Connection health checking (`is_connected`, `ping`)
- [ ] Config integration: read `ai.embabel_url` from `docgen.yaml`
- [ ] Synchronous wrapper for CLI usage (the MCP SDK is async, but docgen CLI is sync)
- [ ] Unit tests with mocked MCP server

## Technical Notes

### MCP Python SDK usage

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client(url="http://localhost:8080/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("generate_narration", arguments={...})
```

### Sync wrapper pattern

Since docgen CLI uses Click (synchronous), we need a sync wrapper:

```python
import asyncio

class EmbabelClientSync:
    def __init__(self, url: str):
        self._async_client = EmbabelClient(url)
        self._loop = asyncio.new_event_loop()

    def invoke(self, tool_name: str, args: dict) -> Any:
        return self._loop.run_until_complete(
            self._async_client.invoke(tool_name, args)
        )
```

### Fallback behavior

```python
def get_ai_provider(config):
    if config.ai_provider == "embabel":
        try:
            client = EmbabelClientSync(config.embabel_url)
            client.connect()
            return EmbabelProvider(client)
        except ConnectionError:
            print("[ai] Embabel unavailable, falling back to OpenAI")
            return OpenAIProvider()
    ...
```

## Files to Create/Modify

- **Create:** `src/docgen/mcp_client.py`
- **Modify:** `src/docgen/ai_provider.py` (implement EmbabelProvider using mcp_client)
- **Modify:** `pyproject.toml` (add `embabel` optional dependency)
- **Create:** `tests/test_mcp_client.py`
