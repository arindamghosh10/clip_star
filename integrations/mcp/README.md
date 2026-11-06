# clip_star MCP server

Lets Claude or any other MCP-capable assistant work with clip_star:

- review clips and fix their post text;
- schedule batches;
- read results, insights and comments;
- with explicit confirmation only, publish and reply.

It talks to clip_star's public API with a personal API key, so the assistant can do only what that key allows.

```bash
pip install ./integrations/mcp
CLIPSTAR_URL=http://localhost:3000 CLIPSTAR_API_KEY=cs_... clipstar-mcp          # stdio
clipstar-mcp --http --port 8765                                                    # Streamable HTTP at /mcp
```

Setup for Claude Code, Claude Desktop and others, and the full tool list: [`docs/API.md`](../../docs/API.md#mcp-server-ai-assistants).

Tests: `pip install -e ".[dev]" && pytest`. The backend suite also runs `clipstar_mcp/api.py` against the real API (`backend/tests/test_mcp_contract.py`).
