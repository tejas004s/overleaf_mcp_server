#!/usr/bin/env bash
set -e
export MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
export MCP_HOST="${MCP_HOST:-127.0.0.1}"
export MCP_PORT="${MCP_PORT:-8000}"
python3 main.py --transport "$MCP_TRANSPORT" --host "$MCP_HOST" --port "$MCP_PORT" "$@"
