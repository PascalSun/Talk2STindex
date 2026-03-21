# Talk2STIndex

Spatiotemporal extraction MCP server powered by [STIndex](https://github.com/MoeBuTa/STIndex/).

## Features

- **MCP Server** with StreamableHTTP transport (MCP protocol 2025-03-26)
- **OAuth 2.0/OIDC** authentication via KAIAPlatform
- **5 extraction tools**: `extract_text`, `extract_file`, `extract_url`, `extract_content`, `analyze`
- **Console UI** for monitoring requests, tools, and latency
- **DuckDB-backed** usage logging and metrics
- **Docker** deployment (CPU + GPU variants)

## Quick Start

```bash
# Setup
./setup.sh --mcp

# Run
source .venv/bin/activate
talk2stindex-mcp sse --port 8016
```

## Docker

```bash
docker compose -f docker-compose.mcp.yml up -d --build
```

## Configuration

Copy `config.mcp.example.yml` to `config.mcp.yml` and update OAuth credentials.
