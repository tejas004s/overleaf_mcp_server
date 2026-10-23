"""FastMCP server implementation for Overleaf Git Bridge integration."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import OverleafConfig
from .git_client import OverleafGitClient
from .latex_parser import (
    analyze_project_references,
    check_latex_syntax,
    compile_latex_locally,
    get_section_content,
    parse_bib_entries,
    parse_sections,
    replace_section_content,
    upsert_bib_entry,
)

mcp = FastMCP(
    "Overleaf MCP Server",
    instructions=(
        "Read, edit, structure, audit, and synchronize Overleaf LaTeX projects "
        "via the official Overleaf Git Bridge."
    ),
)

_client: Optional[OverleafGitClient] = None


def get_client() -> OverleafGitClient:
    """Return or initialize the singleton OverleafGitClient."""
    global _client
    if _client is None:
        _client = OverleafGitClient(OverleafConfig())
    return _client


def set_client(client: OverleafGitClient) -> None:
    """Override the singleton OverleafGitClient (useful for testing)."""
    global _client
    _client = client


def _format_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Project Management & Sync Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def register_project(
    alias: str,
    project_id_or_url: str,
    set_default: bool = True,
) -> str:
    """Register an Overleaf project by its alias and Overleaf Project ID or URL.

    Args:
        alias: Short friendly name for the project (e.g., 'neurips_paper', 'thesis').
        project_id_or_url: Overleaf project URL (https://www.overleaf.com/project/<ID>) or raw ID.
        set_default: Whether to make this the default active project.
    """
    client = get_client()
    resolved = client.config.register_project(alias, project_id_or_url, set_default=set_default)
    return _format_json(
        {
            "registered_alias": alias,
            "project_id": resolved,
            "default_project_id": client.config.default_project_id,
            "all_projects": client.config.projects,
        }
    )


@mcp.tool()
def list_projects() -> str:
    """List all registered Overleaf projects and show configuration status."""
    client = get_client()
    return _format_json(
        {
            "default_project_id": client.config.default_project_id or None,
            "git_token_configured": bool(client.config.git_token),
            "git_base_url": client.config.git_base_url,
            "workspace_dir": str(client.config.workspace_dir),
            "projects": client.config.projects,
        }
    )


@mcp.tool()
def sync_project(project: Optional[str] = None) -> str:
    """Clone or pull the latest changes from Overleaf for the specified project.

    Args:
        project: Optional project alias, ID, or URL. Uses default project if omitted.
    """
    client = get_client()
    repo = client.ensure_repo(project=project, auto_pull=False)
    pull_output = client.pull(project=project, repo_path=repo)
    files = client.list_files(project=project, auto_pull=False)
    return _format_json(
        {
            "project": client.config.resolve_project_id(project),
            "pull_result": pull_output,
            "file_count": len(files),
            "files": [f["path"] for f in files],
        }
    )


@mcp.tool()
def get_project_status(project: Optional[str] = None, history_limit: int = 10) -> str:
    """Inspect the Git status, uncommitted diffs, and recent commit history of an Overleaf project.

    Args:
        project: Optional project alias or ID.
        history_limit: Number of recent commits to return (default 10).
    """
    client = get_client()
    status_diff = client.status_and_diff(project=project)
    history = client.get_history(project=project, limit=history_limit)
    return _format_json(
        {
            "project": client.config.resolve_project_id(project),
            "git_status": status_diff["status"],
            "uncommitted_diff": status_diff["diff"],
            "recent_commits": history,
        }
    )


# ---------------------------------------------------------------------------
# File Operations Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_files(
    project: Optional[str] = None,
    extension_filter: Optional[str] = None,
) -> str:
    """List files in the Overleaf project (automatically pulls latest changes first).

    Args:
        project: Optional project alias or ID.
        extension_filter: Optional suffix filter such as '.tex' or '.bib'.
    """
    client = get_client()
    files = client.list_files(project=project, extension_filter=extension_filter, auto_pull=True)
    return _format_json(
        {
            "project": client.config.resolve_project_id(project),
            "count": len(files),
            "files": files,
        }
    )


@mcp.tool()
def read_file(file_path: str = "main.tex", project: Optional[str] = None) -> str:
    """Read the full contents of a file in the Overleaf project.

    Args:
        file_path: Relative path to the file inside the project (default 'main.tex').
        project: Optional project alias or ID.
    """
    client = get_client()
    return client.read_file(file_path=file_path, project=project, auto_pull=True)


@mcp.tool()
def write_file(
    file_path: str,
    content: str,
    commit_message: Optional[str] = None,
    auto_push: bool = True,
    project: Optional[str] = None,
) -> str:
    """Create or overwrite a file in the Overleaf project and optionally commit & push to Overleaf.

    Args:
        file_path: Relative path to the file (e.g., 'main.tex', 'sections/intro.tex').
        content: Complete text content to write to the file.
        commit_message: Custom Git commit message for Overleaf history.
        auto_push: If True (default), immediately commits and pushes changes to Overleaf.
        project: Optional project alias or ID.
    """
    client = get_client()
    res = client.write_file(
        file_path=file_path,
        content=content,
        project=project,
        commit_message=commit_message,
        auto_push=auto_push,
    )
    return _format_json(res)


@mcp.tool()
def edit_file_snippet(
    file_path: str,
    target_text: str,
    replacement_text: str,
    commit_message: Optional[str] = None,
    auto_push: bool = True,
    project: Optional[str] = None,
) -> str:
    """Replace an exact snippet of text inside a project file and sync back to Overleaf.

    Args:
        file_path: Relative path to the file (e.g., 'main.tex').
        target_text: Exact substring to find in the file (must occur uniquely).
        replacement_text: New text to replace target_text with.
        commit_message: Optional commit message.
        auto_push: If True (default), immediately commits and pushes to Overleaf.
        project: Optional project alias or ID.
    """
    client = get_client()
    current = client.read_file(file_path=file_path, project=project, auto_pull=True)
    occurrences = current.count(target_text)
    if occurrences == 0:
        raise ValueError(f"target_text was not found in '{file_path}'.")
    if occurrences > 1:
        raise ValueError(
            f"target_text matched {occurrences} locations in '{file_path}'. "
            "Provide more surrounding context lines to make it unique."
        )

    updated = current.replace(target_text, replacement_text, 1)
    msg = commit_message or f"Edit snippet in {file_path} via Overleaf MCP"
    res = client.write_file(
        file_path=file_path,
        content=updated,
        project=project,
        commit_message=msg,
        auto_push=auto_push,
    )
    return _format_json(res)


@mcp.tool()
def delete_file(
    file_path: str,
    commit_message: Optional[str] = None,
    auto_push: bool = True,
    project: Optional[str] = None,
) -> str:
    """Delete a file from the Overleaf project and optionally push the deletion.

    Args:
        file_path: Relative path to the file to delete.
        commit_message: Optional Git commit message.
        auto_push: If True (default), commits and pushes the deletion to Overleaf.
        project: Optional project alias or ID.
    """
    client = get_client()
    res = client.delete_file(
        file_path=file_path,
        project=project,
        commit_message=commit_message,
        auto_push=auto_push,
    )
    return _format_json(res)


@mcp.tool()
def push_changes(
    commit_message: str = "Update from Overleaf MCP",
    project: Optional[str] = None,
) -> str:
    """Commit and push any pending local changes back to Overleaf.

    Args:
        commit_message: Commit message describing the changes.
        project: Optional project alias or ID.
    """
    client = get_client()
    res = client.commit_and_push(message=commit_message, project=project)
    return _format_json(res)


# ---------------------------------------------------------------------------
# LaTeX Structure, Sections, BibTeX & Validation Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_document_outline(
    file_path: str = "main.tex",
    project: Optional[str] = None,
) -> str:
    """Parse a LaTeX file and return its hierarchical section outline with line numbers.

    Args:
        file_path: Relative path to the .tex file (default 'main.tex').
        project: Optional project alias or ID.
    """
    client = get_client()
    content = client.read_file(file_path=file_path, project=project, auto_pull=True)
    sections = parse_sections(content)
    return _format_json(
        {
            "file_path": file_path,
            "section_count": len(sections),
            "sections": [
                {
                    "index": s.index,
                    "command": f"\\{s.command}",
                    "title": s.title,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                }
                for s in sections
            ],
        }
    )


@mcp.tool()
def read_section(
    title_or_index: str,
    file_path: str = "main.tex",
    project: Optional[str] = None,
) -> str:
    """Read a specific section from a LaTeX file by its section title or 0-based index.

    Args:
        title_or_index: Section title (e.g., 'Introduction', 'Related Work') or index ('0', '1').
        file_path: Relative path to the .tex file (default 'main.tex').
        project: Optional project alias or ID.
    """
    client = get_client()
    content = client.read_file(file_path=file_path, project=project, auto_pull=True)
    sec = get_section_content(content, title_or_index)
    return _format_json(sec)


@mcp.tool()
def update_section(
    title_or_index: str,
    new_content: str,
    file_path: str = "main.tex",
    commit_message: Optional[str] = None,
    auto_push: bool = True,
    project: Optional[str] = None,
) -> str:
    """Replace the content of a specific LaTeX section (including its \\section{...} header) and sync to Overleaf.

    Args:
        title_or_index: Section title or 0-based section index to replace.
        new_content: Full replacement LaTeX text for the section (including the \\section{...} line).
        file_path: Relative path to the .tex file (default 'main.tex').
        commit_message: Optional Git commit message.
        auto_push: If True (default), commits and pushes the updated section to Overleaf.
        project: Optional project alias or ID.
    """
    client = get_client()
    content = client.read_file(file_path=file_path, project=project, auto_pull=True)
    replaced = replace_section_content(content, title_or_index, new_content)
    msg = commit_message or f"Update section '{replaced['replaced_section']}' in {file_path}"
    write_res = client.write_file(
        file_path=file_path,
        content=replaced["updated_content"],
        project=project,
        commit_message=msg,
        auto_push=auto_push,
    )
    return _format_json(
        {
            "replaced_section": replaced["replaced_section"],
            "old_line_range": replaced["old_line_range"],
            **write_res,
        }
    )


@mcp.tool()
def list_bibliography(
    bib_file: str = "references.bib",
    query: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Parse and optionally search BibTeX entries in a .bib file.

    Args:
        bib_file: Relative path to the .bib file (default 'references.bib').
        query: Optional search substring matching citation key, title, author, or year.
        project: Optional project alias or ID.
    """
    client = get_client()
    bib_text = client.read_file(file_path=bib_file, project=project, auto_pull=True)
    entries = parse_bib_entries(bib_text)
    if query:
        q = query.lower().strip()
        entries = [
            e
            for e in entries
            if q in e["key"].lower()
            or q in e["title"].lower()
            or q in e["author"].lower()
            or q in e["year"].lower()
        ]
    return _format_json(
        {
            "bib_file": bib_file,
            "count": len(entries),
            "entries": entries,
        }
    )


@mcp.tool()
def add_or_update_bib_entry(
    raw_bibtex: str,
    bib_file: str = "references.bib",
    commit_message: Optional[str] = None,
    auto_push: bool = True,
    project: Optional[str] = None,
) -> str:
    """Insert a new BibTeX entry or update an existing one by key in a .bib file.

    Args:
        raw_bibtex: Complete BibTeX entry string (e.g. '@article{vaswani2017attention, ...}').
        bib_file: Relative path to the .bib file (default 'references.bib').
        commit_message: Optional Git commit message.
        auto_push: If True (default), commits and pushes the updated .bib file to Overleaf.
        project: Optional project alias or ID.
    """
    client = get_client()
    repo = client.ensure_repo(project=project, auto_pull=True)
    target = client.resolve_safe_file(repo, bib_file)
    existing_text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""

    res = upsert_bib_entry(existing_text, raw_bibtex)
    msg = commit_message or f"{res['action'].capitalize()} BibTeX entry '{res['key']}' in {bib_file}"
    write_res = client.write_file(
        file_path=bib_file,
        content=res["content"],
        project=project,
        commit_message=msg,
        auto_push=auto_push,
    )
    return _format_json(
        {
            "key": res["key"],
            "action": res["action"],
            **write_res,
        }
    )


@mcp.tool()
def audit_references_and_citations(project: Optional[str] = None) -> str:
    """Audit all .tex and .bib files in the project for missing citations, broken \\ref links, unused BibTeX entries, and duplicate labels.

    Args:
        project: Optional project alias or ID.
    """
    client = get_client()
    repo = client.ensure_repo(project=project, auto_pull=True)
    report = analyze_project_references(repo)
    return _format_json(report)


@mcp.tool()
def validate_and_compile(
    main_tex: str = "main.tex",
    project: Optional[str] = None,
) -> str:
    """Validate LaTeX syntax (unclosed environments, unbalanced braces) and run local PDF compilation if latexmk/pdflatex is installed.

    Args:
        main_tex: Main .tex file to validate and compile (default 'main.tex').
        project: Optional project alias or ID.
    """
    client = get_client()
    repo = client.ensure_repo(project=project, auto_pull=True)
    tex_content = client.read_file(file_path=main_tex, project=project, auto_pull=False)
    syntax = check_latex_syntax(tex_content)
    compile_res = compile_latex_locally(repo, main_tex=main_tex)
    return _format_json(
        {
            "main_tex": main_tex,
            "syntax_check": syntax,
            "compilation": compile_res,
        }
    )


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------


@mcp.prompt()
def review_paper_section(section_title: str, file_path: str = "main.tex") -> str:
    """Prompt workflow to read, review, and polish a specific section of an Overleaf paper."""
    return (
        f"Please read section '{section_title}' from '{file_path}' using the `read_section` tool. "
        "Review it for clarity, academic tone, mathematical precision, and LaTeX formatting. "
        "Propose concrete improvements and ask if I would like you to apply them to Overleaf using `update_section`."
    )


@mcp.prompt()
def audit_paper_quality(main_tex: str = "main.tex") -> str:
    """Prompt workflow to run a comprehensive citation, reference, and syntax audit on the Overleaf project."""
    return (
        f"Please run `audit_references_and_citations` and `validate_and_compile` (on '{main_tex}') "
        "for my Overleaf project. Summarize any missing citations, broken `\\ref` links, duplicate labels, "
        "or LaTeX syntax errors, and help me fix them."
    )


# ---------------------------------------------------------------------------
# HTTP / SSE / Streamable-HTTP App Factory & Entrypoint
# ---------------------------------------------------------------------------


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Optional Bearer token / X-API-Key authentication middleware for remote HTTP/SSE deployments."""

    def __init__(self, app: Any, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.url.path == "/health" or request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")
        query_key = request.query_params.get("api_key", "")

        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        elif api_key_header:
            token = api_key_header.strip()
        elif query_key:
            token = query_key.strip()

        if token != self.api_key:
            return JSONResponse(
                {"error": "Unauthorized. Provide a valid Bearer token in Authorization header."},
                status_code=401,
            )
        return await call_next(request)


def create_http_app(transport: str = "streamable-http", api_key: Optional[str] = None) -> Starlette:
    """Create a Starlette ASGI application wrapping the FastMCP server with /health and CORS."""
    if transport == "sse":
        mcp_app = mcp.sse_app()
    else:
        mcp_app = mcp.streamable_http_app()

    async def health_endpoint(_request: Request) -> JSONResponse:
        client = get_client()
        return JSONResponse(
            {
                "status": "ok",
                "server": "overleaf-mcp-server",
                "transport": transport,
                "git_token_configured": bool(client.config.git_token),
                "default_project_id": client.config.default_project_id or None,
            }
        )

    middlewares = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]
    effective_key = api_key if api_key is not None else os.getenv("MCP_API_KEY", "").strip()
    if effective_key:
        middlewares.append(Middleware(BearerAuthMiddleware, api_key=effective_key))

    routes = [
        Route("/health", endpoint=health_endpoint, methods=["GET"]),
        Mount("/", app=mcp_app),
    ]

    lifespan = getattr(mcp_app, "lifespan", None) or getattr(mcp_app.router, "lifespan_context", None)
    return Starlette(routes=routes, middleware=middlewares, lifespan=lifespan)


def main() -> None:
    """CLI entrypoint for overleaf-mcp."""
    parser = argparse.ArgumentParser(description="Overleaf MCP Server (stdio, sse, streamable-http)")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="MCP transport protocol (default: stdio, or MCP_TRANSPORT env var)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="Host address to bind when using sse or streamable-http (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", os.getenv("PORT", "8000"))),
        help="Port to bind when using sse or streamable-http (default: 8000)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn

        app = create_http_app(transport=args.transport)
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
