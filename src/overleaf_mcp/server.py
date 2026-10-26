"""Overleaf MCP Server (Free-Tier Playwright Browser Automation + Git Bridge + Cloud Deployment)."""

from __future__ import annotations

import argparse
import json
import os
import traceback
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
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route

from .browser_client import OVERLEAF_OUTPUT_DIR, PUBLIC_URL, SERVER_HOST, SERVER_PORT, TRANSPORT
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
    "overleaf-latex-mcp",
    instructions=(
        "Connects Claude, ChatGPT, and Gemini to Overleaf (via Free-Tier Playwright Browser Automation "
        "or Overleaf Git Bridge) to tailor LaTeX resumes/papers, edit sections, manage BibTeX citations, "
        "recompile, and return clickable PDF download links."
    ),
)

_client: Optional[OverleafGitClient] = None


def get_client() -> OverleafGitClient:
    """Return or initialize the singleton OverleafGitClient (which also owns browser_client)."""
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


def _build_download_url(request: Optional[Request], filename: str) -> str:
    """Build the full absolute download URL, preferring PUBLIC_URL / RAILWAY_PUBLIC_DOMAIN."""
    if PUBLIC_URL:
        return f"{PUBLIC_URL}/download/{filename}"
    base = str(request.base_url).rstrip("/") if request else ""
    return f"{base}/download/{filename}" if base else f"/download/{filename}"


# ---------------------------------------------------------------------------
# Web Dashboard & PDF Download Routes (for Railway / Render / Local HTTP)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Overleaf MCP Server - Easy Setup & Test Console</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 30px 20px; display: flex; justify-content: center; }
        .container { max-width: 820px; width: 100%; background: #1e293b; border-radius: 12px; padding: 28px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid #334155; }
        h1 { margin-top: 0; color: #38bdf8; font-size: 24px; display: flex; align-items: center; justify-content: space-between; }
        .badge { background: #10b981; color: #022c22; font-size: 13px; font-weight: 700; padding: 4px 12px; border-radius: 9999px; }
        .endpoint-card { background: #0f172a; border-left: 4px solid #38bdf8; padding: 14px 16px; margin: 12px 0 18px; border-radius: 6px; font-family: monospace; font-size: 14px; display: flex; align-items: center; justify-content: space-between; gap: 12px; word-break: break-all; }
        .section { background: #0f172a; border-radius: 8px; padding: 18px; margin-top: 20px; border: 1px solid #334155; }
        h2 { font-size: 16px; color: #38bdf8; margin-top: 0; letter-spacing: 0.03em; }
        label { display: block; font-size: 13px; color: #94a3b8; margin-bottom: 6px; font-weight: 600; }
        button { background: #2563eb; color: white; border: none; padding: 10px 18px; border-radius: 6px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
        button:hover { background: #1d4ed8; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        input { width: 100%; padding: 10px 14px; background: #1e293b; border: 1px solid #475569; border-radius: 6px; color: white; font-size: 14px; margin-bottom: 14px; }
        pre { background: #020617; padding: 14px; border-radius: 6px; overflow-x: auto; color: #38bdf8; font-size: 13px; max-height: 260px; }
        .status-indicator { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #10b981; margin-right: 8px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>
            <span>📄 Overleaf MCP Server</span>
            <span class="badge"><span class="status-indicator"></span>ONLINE</span>
        </h1>

        <p style="color: #94a3b8; margin-bottom: 4px;">1. Copy this MCP URL into <b>Claude (Settings &rarr; Integrations)</b>:</p>
        <div class="endpoint-card">
            <span id="mcp-url">Loading...</span>
            <button onclick="copyMcpUrl()" id="btn-copy" style="padding: 6px 12px; font-size: 12px;">Copy URL</button>
        </div>

        <div class="section">
            <h2>⚡ 2. Connect Your Overleaf Project (No Terminal Needed)</h2>
            <label>Overleaf Project / Share Link URL:</label>
            <input type="text" id="cfg-share-url" value="https://www.overleaf.com/project/6ab69fcdfed103759283b936/share#1145d72d9449b66e08f0f68750a29a9d05489b403ed59b83" />

            <label>Overleaf Session Cookie (Optional — only if Overleaf asks for login):</label>
            <input type="password" id="cfg-cookie" placeholder="Paste 'overleaf_session2' value from Browser DevTools -> Application -> Cookies" />

            <button id="btn-save" onclick="saveConfig()">Save &amp; Test Connection</button>
            <pre id="save-output" style="display:none;"></pre>
        </div>

        <div class="section">
            <h2>🧪 3. Live LaTeX Read Test</h2>
            <p style="color: #cbd5e1; font-size: 14px; margin-top: 0;">Verify that the server can open your Overleaf project and read the LaTeX source.</p>
            <button id="btn-project" onclick="testProject()">Open Project &amp; Read LaTeX</button>
            <pre id="project-output" style="display:none;"></pre>
        </div>
    </div>

    <script>
        const mcpUrl = window.location.origin + '/mcp';
        document.getElementById('mcp-url').innerText = mcpUrl;

        function copyMcpUrl() {
            navigator.clipboard.writeText(mcpUrl);
            const b = document.getElementById('btn-copy');
            b.innerText = 'Copied!';
            setTimeout(() => b.innerText = 'Copy URL', 2000);
        }

        async function saveConfig() {
            const btn = document.getElementById('btn-save');
            const out = document.getElementById('save-output');
            const shareUrl = document.getElementById('cfg-share-url').value.trim();
            const cookie = document.getElementById('cfg-cookie').value.trim();
            btn.disabled = true;
            btn.innerText = 'Saving & Connecting...';
            out.style.display = 'block';
            out.innerText = 'Updating session and checking Overleaf access...';
            try {
                const res = await fetch('/api/configure', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ share_url: shareUrl, session_cookie: cookie })
                });
                const data = await res.json();
                out.innerText = JSON.stringify(data, null, 2);
            } catch(e) {
                out.innerText = 'Error: ' + e.message;
            }
            btn.disabled = false;
            btn.innerText = 'Save & Test Connection';
        }

        async function testProject() {
            const input = document.getElementById('cfg-share-url').value.trim();
            const btn = document.getElementById('btn-project');
            const out = document.getElementById('project-output');
            btn.disabled = true;
            btn.innerText = 'Opening project...';
            out.style.display = 'block';
            out.innerText = 'Launching browser, navigating to Overleaf project and extracting LaTeX...';
            try {
                const res = await fetch('/api/test-project', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ project_url: input })
                });
                const data = await res.json();
                out.innerText = JSON.stringify(data, null, 2);
            } catch(e) {
                out.innerText = 'Error: ' + e.message;
            }
            btn.disabled = false;
            btn.innerText = 'Open Project & Read LaTeX';
        }
    </script>
</body>
</html>
"""


async def root_dashboard(_request: Request) -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


async def download_file_endpoint(request: Request) -> Any:
    filename = request.path_params.get("filename", "")
    file_path = OVERLEAF_OUTPUT_DIR / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/pdf",
        )
    return HTMLResponse("<h3>File not found</h3>", status_code=404)


async def api_test_auth(_request: Request) -> JSONResponse:
    res = await get_client().browser_client.check_auth_status()
    return JSONResponse(res)


async def api_test_project(request: Request) -> JSONResponse:
    try:
        data = await request.json()
        project_url = data.get("project_url", "")
        bclient = get_client().browser_client
        open_res = await bclient.open_project(project_url)
        if not open_res.get("success"):
            return JSONResponse(open_res)
        latex_res = await bclient.get_latex_content()
        full_latex = latex_res.get("latex") or ""
        return JSONResponse(
            {
                "open_result": open_res,
                "latex_success": latex_res.get("success"),
                "line_count": len(full_latex.splitlines()),
                "latex_preview": full_latex[:600]
                + ("\n... [truncated for display]" if len(full_latex) > 600 else ""),
            }
        )
    except Exception as exc:
        return JSONResponse(
            {
                "success": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
            status_code=200,
        )


async def health_check_route(_request: Request) -> JSONResponse:
    client = get_client()
    return JSONResponse(
        {
            "status": "ok",
            "server": "overleaf-mcp-server",
            "default_project_id": client.config.default_project_id or None,
        }
    )


async def api_configure(request: Request) -> JSONResponse:
    try:
        data = await request.json()
        bclient = get_client().browser_client
        cfg_res = await bclient.configure_session(
            share_url=data.get("share_url"),
            session_cookie=data.get("session_cookie"),
            storage_state_b64=data.get("storage_state_b64"),
        )
        auth_res = await bclient.check_auth_status()
        return JSONResponse({"configured": cfg_res, "auth_status": auth_res})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=200)


# Register custom routes directly on MCPServer if supported (mcp >= 2.0)
if hasattr(mcp, "custom_route"):
    mcp.custom_route("/", methods=["GET"])(root_dashboard)
    mcp.custom_route("/health", methods=["GET"])(health_check_route)
    mcp.custom_route("/download/{filename}", methods=["GET"])(download_file_endpoint)
    mcp.custom_route("/api/configure", methods=["POST"])(api_configure)
    mcp.custom_route("/api/test-auth", methods=["GET"])(api_test_auth)
    mcp.custom_route("/api/test-project", methods=["POST"])(api_test_project)


# ---------------------------------------------------------------------------
# Browser-Native Overleaf Tools (Works on Free Tier & Cloud Deployments)
# ---------------------------------------------------------------------------


@mcp.tool()
async def overleaf_configure_session(
    share_url: Optional[str] = None,
    session_cookie: Optional[str] = None,
) -> str:
    """Configure your Overleaf Share URL or Overleaf session cookie directly from Claude chat (no terminal or env vars required).

    Args:
        share_url: Overleaf project URL or link-sharing edit URL (e.g. 'https://www.overleaf.com/project/.../share#...').
        session_cookie: Optional 'overleaf_session2' cookie value if Overleaf requires authentication.
    """
    bclient = get_client().browser_client
    cfg = await bclient.configure_session(share_url=share_url, session_cookie=session_cookie)
    status = await bclient.check_auth_status()
    return _format_json({"configuration": cfg, "auth_status": status})


@mcp.tool()
async def overleaf_status() -> str:
    """Check the connection status and whether the user is authenticated in Overleaf.
    Call this first to verify that your session is ready.
    """
    res = await get_client().browser_client.check_auth_status()
    return _format_json(res)


@mcp.tool()
async def overleaf_open_project(project_url_or_id: str) -> str:
    """Open an Overleaf project by its URL, share link, or 24-character Project ID.
    Example: 'https://www.overleaf.com/project/6ab69f.../share#...' or '6ab69f...'
    Returns project title, current open file name, and status.
    """
    res = await get_client().browser_client.open_project(project_url_or_id)
    return _format_json(res)


@mcp.tool()
async def overleaf_create_blank_project(project_name: str = "Tailored_Resume") -> str:
    """Create a brand-new Blank Project on Overleaf and open it in the editor.

    Args:
        project_name: Name for the new Overleaf project (default 'Tailored_Resume').
    """
    res = await get_client().browser_client.create_blank_project(project_name=project_name)
    return _format_json(res)


@mcp.tool()
def get_resume_latex_template() -> str:
    """Return a complete, self-contained 1-page ATS-friendly LaTeX resume template (single main.tex, no external .cls required) ready to customize and pass to overleaf_set_latex."""
    return r"""\documentclass[10pt,letterpaper]{article}
\usepackage[left=0.5in,top=0.45in,right=0.5in,bottom=0.45in]{geometry}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{titlesec}
\pagenumbering{gobble}

\titleformat{\section}{\large\bfseries\uppercase}{}{0em}{}[\titlerule]
\titlespacing{\section}{0pt}{8pt}{4pt}
\setlist[itemize]{noitemsep, topsep=2pt, leftmargin=1.5em}

\begin{document}

\begin{center}
    {\LARGE \textbf{YOUR FULL NAME}} \\[3pt]
    City, Country $\cdot$ \href{mailto:you@example.com}{you@example.com} $\cdot$ +1-555-010-9999 $\cdot$ \href{https://linkedin.com/in/yourprofile}{linkedin.com/in/yourprofile} $\cdot$ \href{https://github.com/yourgithub}{github.com/yourgithub}
\end{center}

\section{Education}
\textbf{University Name} \hfill \textbf{City, Country} \\
\textit{B.Tech / M.S. in Computer Science \& Engineering (GPA: X.XX/10.0)} \hfill \textit{Aug 2022 -- May 2026}

\section{Technical Skills}
\begin{itemize}
    \item \textbf{Languages:} Python, TypeScript, C++, SQL, Bash
    \item \textbf{Frameworks \& Libraries:} PyTorch, FastAPI, React, Node.js, LangChain, Model Context Protocol (MCP)
    \item \textbf{Cloud \& DevOps:} Docker, AWS, Git, Linux, PostgreSQL, Redis, CI/CD
\end{itemize}

\section{Experience}
\textbf{Company Name} $|$ \textit{Software / Machine Learning Engineer Intern} \hfill \textit{May 2025 -- Aug 2025}
\begin{itemize}
    \item Designed and deployed production microservices in Python/FastAPI handling 50K+ daily requests with 99.9\% uptime.
    \item Automated document and workflow pipelines using LLM agents and Playwright browser automation, reducing manual processing time by 65\%.
    \item Optimized SQL queries and Redis caching layers, cutting p95 API latency from 420ms to 110ms.
\end{itemize}

\section{Projects}
\textbf{Overleaf \& LinkedIn MCP Servers} $|$ \textit{Python, FastMCP, Playwright, Docker} \hfill \textit{2026}
\begin{itemize}
    \item Built cloud-deployed Model Context Protocol (MCP) servers enabling Claude, ChatGPT, and Gemini to automate Overleaf LaTeX authoring and LinkedIn Easy Apply workflows.
    \item Engineered direct CodeMirror 6 state injection and real-time PDF compilation/download pipelines.
\end{itemize}

\end{document}
"""


@mcp.tool()
async def overleaf_list_files() -> str:
    """List all the files and folders in the currently open Overleaf project file tree.
    Useful for locating 'main.tex', 'resume.cls', or modular section files.
    """
    res = await get_client().browser_client.list_files()
    return _format_json(res)


@mcp.tool()
async def overleaf_open_file(filename: str) -> str:
    """Switch the Overleaf editor to a specific file in the project (e.g., 'main.tex', 'references.bib')."""
    res = await get_client().browser_client.open_file(filename)
    return _format_json(res)


@mcp.tool()
async def overleaf_get_latex() -> str:
    """Read and return the complete LaTeX source code currently open in the Overleaf editor."""
    res = await get_client().browser_client.get_latex_content()
    return _format_json(res)


@mcp.tool()
async def overleaf_set_latex(latex_code: str) -> str:
    """Replace the Overleaf editor content with the updated LaTeX code.
    Overleaf will automatically synchronize and autosave the changes.
    """
    res = await get_client().browser_client.set_latex_content(latex_code)
    return _format_json(res)


@mcp.tool()
async def overleaf_recompile(timeout_seconds: int = 35) -> str:
    """Trigger the 'Recompile' action in Overleaf and check for compilation errors or warnings.
    Always call this after updating LaTeX code to ensure there are no syntax or formatting errors.
    """
    res = await get_client().browser_client.recompile(timeout_seconds=timeout_seconds)
    return _format_json(res)


@mcp.tool()
async def overleaf_download_pdf(filename: Optional[str] = None) -> str:
    """Download the freshly compiled PDF from Overleaf to the server and return a clickable download_url."""
    res = await get_client().browser_client.download_pdf(custom_filename=filename)
    if res.get("success") and "file_name" in res:
        full_url = _build_download_url(None, res["file_name"])
        res["download_url"] = full_url
        res["action_for_claude"] = (
            f"Present this exact clickable link to the user: "
            f"[Download Compiled PDF]({full_url})  "
            f"The URL is: {full_url}"
        )
    return _format_json(res)


@mcp.tool()
async def overleaf_take_screenshot(filename: Optional[str] = None) -> str:
    """Take a screenshot of the Overleaf page (editor or PDF preview) and save it locally."""
    res = await get_client().browser_client.take_screenshot(filename=filename)
    return _format_json(res)


@mcp.tool()
def tailor_resume_instructions() -> str:
    """Return guidance and best practices for tailoring a LaTeX resume to a Job Description (JD)."""
    instructions = {
        "latex_safety": [
            "Always escape special LaTeX characters: &, %, $, #, _, {, }, ~, ^",
            "Keep LaTeX environment tags matched: \\begin{itemize} ... \\end{itemize}",
            "Preserve page constraints (usually strict 1 page or 2 pages) by avoiding excessive line additions",
            "Maintain typography commands (e.g. \\textbf, \\textit, \\small, \\hfill) according to the template",
        ],
        "tailoring_strategy": [
            "Extract top 5-10 technical and domain keywords from the JD (technologies, methodologies, leadership words)",
            "Weave keywords naturally into existing experience bullets rather than keyword-stuffing",
            "Use the Google XYZ bullet formula: 'Accomplished [X] as measured by [Y], by doing [Z]'",
            "Update the Skills section to prioritize tech stack items that match the JD requirements",
            "Customize the Summary/Header subtitle (if present) to align with the target job title",
        ],
        "workflow": [
            "1. Call overleaf_open_project with user's project URL",
            "2. Call overleaf_get_latex to retrieve source resume",
            "3. Analyze JD against the resume and draft tailored changes",
            "4. Call overleaf_set_latex with the complete updated LaTeX code",
            "5. Call overleaf_recompile to verify zero compile errors",
            "6. Call overleaf_download_pdf to deliver the final PDF link to the user",
            "7. Return a summary of tailored keywords, updated bullets, and ATS optimization score",
        ],
    }
    return _format_json(instructions)


@mcp.tool()
def launch_overleaf_browser(
    share_or_project_url: Optional[str] = None,
    port: int = 9222,
) -> str:
    """Launch Google Chrome with Remote Debugging (--remote-debugging-port=9222) for interactive Overleaf login.

    Args:
        share_or_project_url: Optional Overleaf project or share URL to open immediately.
        port: Chrome Remote Debugging port (default 9222).
    """
    client = get_client()
    res = client.browser_client.launch_chrome_debug_session(
        port=port,
        target_url=share_or_project_url,
    )
    return _format_json(res)


@mcp.tool()
async def check_overleaf_browser_session(
    share_or_project_url: Optional[str] = None,
) -> str:
    """Verify that Chrome is connected and the Free-Tier Overleaf project is open in the browser.

    Args:
        share_or_project_url: Optional Overleaf project or share URL to navigate to.
    """
    client = get_client()
    res = await client.browser_client.open_project(share_or_project_url)
    return _format_json(res)


# ---------------------------------------------------------------------------
# Project Management, File Sync, Section & BibTeX Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def register_project(
    alias: str,
    project_id_or_url: str,
    set_default: bool = True,
) -> str:
    """Register an Overleaf project by its alias and Overleaf Project ID or URL."""
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
    """Clone or pull the latest changes from Overleaf for the specified project."""
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
    """Inspect the Git status, uncommitted diffs, and recent commit history of an Overleaf project."""
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


@mcp.tool()
def list_files(
    project: Optional[str] = None,
    extension_filter: Optional[str] = None,
) -> str:
    """List files in the Overleaf project workspace."""
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
    """Read the full contents of a file in the Overleaf project."""
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
    """Create or overwrite a file in the Overleaf project and sync back to Overleaf."""
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
    """Replace an exact snippet of text inside a project file and sync back to Overleaf."""
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
    """Delete a file from the Overleaf project and optionally push the deletion."""
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
    """Commit and push any pending local changes back to Overleaf."""
    client = get_client()
    res = client.commit_and_push(message=commit_message, project=project)
    return _format_json(res)


@mcp.tool()
def get_document_outline(
    file_path: str = "main.tex",
    project: Optional[str] = None,
) -> str:
    """Parse a LaTeX file and return its hierarchical section outline with line numbers."""
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
    """Read a specific section from a LaTeX file by its section title or 0-based index."""
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
    """Replace the content of a specific LaTeX section (including its \\section{...} header) and sync to Overleaf."""
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
    """Parse and optionally search BibTeX entries in a .bib file."""
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
    """Insert a new BibTeX entry or update an existing one by key in a .bib file."""
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
    """Audit all .tex and .bib files in the project for missing citations, broken \\ref links, unused BibTeX entries, and duplicate labels."""
    client = get_client()
    repo = client.ensure_repo(project=project, auto_pull=True)
    report = analyze_project_references(repo)
    return _format_json(report)


@mcp.tool()
def validate_and_compile(
    main_tex: str = "main.tex",
    project: Optional[str] = None,
) -> str:
    """Validate LaTeX syntax (unclosed environments, unbalanced braces) and run local PDF compilation if latexmk/pdflatex is installed."""
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
# HTTP / SSE / Streamable-HTTP App Factory & Entrypoint
# ---------------------------------------------------------------------------


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Optional Bearer token / X-API-Key authentication middleware for remote HTTP/SSE deployments."""

    def __init__(self, app: Any, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.url.path in ("/", "/health", "/api/configure", "/api/test-auth", "/api/test-project") or request.url.path.startswith("/download/") or request.method == "OPTIONS":
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
    """Create a Starlette ASGI application wrapping the MCPServer with test console, /download, and /health."""
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
        Route("/", endpoint=root_dashboard, methods=["GET"]),
        Route("/health", endpoint=health_endpoint, methods=["GET"]),
        Route("/download/{filename}", endpoint=download_file_endpoint, methods=["GET"]),
        Route("/api/configure", endpoint=api_configure, methods=["POST"]),
        Route("/api/test-auth", endpoint=api_test_auth, methods=["GET"]),
        Route("/api/test-project", endpoint=api_test_project, methods=["POST"]),
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
        default=SERVER_HOST,
        help=f"Host address to bind when using sse or streamable-http (default: {SERVER_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=SERVER_PORT,
        help=f"Port to bind when using sse or streamable-http (default: {SERVER_PORT})",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run Playwright browser in visible mode (default is headless in cloud, configurable via OVERLEAF_HEADLESS)",
    )
    args = parser.parse_args()

    if args.no_headless:
        os.environ["OVERLEAF_HEADLESS"] = "false"
        get_client().browser_client.headless = False

    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        try:
            from mcp.server.transport_security import TransportSecuritySettings

            security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
            if args.transport == "sse":
                mcp.run("sse", host=args.host, port=args.port, transport_security=security_settings)
            else:
                mcp.run(
                    "streamable-http",
                    host=args.host,
                    port=args.port,
                    transport_security=security_settings,
                )
        except (ImportError, TypeError):
            import uvicorn

            app = create_http_app(transport=args.transport)
            uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
