#!/usr/bin/env python3
"""
Overleaf MCP Server Cloud & Local HTTP Entrypoint (Railway / Render / Claude / ChatGPT / Gemini).
Defaults to `streamable-http` when invoked via `python3 main.py` (or uses `MCP_TRANSPORT`).
"""

import argparse
import os
import sys

from overleaf_mcp.browser_client import HEADLESS, SERVER_HOST, SERVER_PORT


def main() -> None:
    default_transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    parser = argparse.ArgumentParser(description="Overleaf MCP Server for Claude, ChatGPT & Gemini")
    parser.add_argument(
        "--transport",
        choices=["sse", "stdio", "streamable-http"],
        default=default_transport,
        help="MCP Transport protocol: 'streamable-http' (default for cloud/web), 'sse', or 'stdio'",
    )
    parser.add_argument(
        "--host",
        default=SERVER_HOST,
        help=f"Host address for HTTP/SSE server (default: {SERVER_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=SERVER_PORT,
        help=f"Port number for HTTP/SSE server (default: {SERVER_PORT})",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible mode (default is headless in cloud)",
    )
    args = parser.parse_args()

    if args.no_headless:
        os.environ["OVERLEAF_HEADLESS"] = "false"

    from overleaf_mcp.server import create_http_app, get_client, mcp

    browser = get_client().browser_client
    if args.no_headless:
        browser.headless = False

    if args.transport != "stdio":
        print("=" * 60)
        print("🚀 Overleaf MCP Server starting...")
        print(f"📦 Transport : {args.transport}")
        print(f"🌐 Host      : {args.host}")
        print(f"🔌 Port      : {args.port}")
        if args.transport == "streamable-http":
            print(f"📡 MCP URL   : http://{args.host}:{args.port}/mcp")
        else:
            print(f"📡 SSE URL   : http://{args.host}:{args.port}/sse")
        print(f"🧪 Console   : http://{args.host}:{args.port}/")
        print(f"🖥️  Headless  : {browser.headless}")
        print("=" * 60)

    try:
        if args.transport == "stdio":
            mcp.run("stdio")
            return

        import uvicorn

        app = create_http_app(transport=args.transport)
        uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")
    except KeyboardInterrupt:
        print("\nShutting down Overleaf MCP Server...")
        sys.exit(0)


if __name__ == "__main__":
    main()
