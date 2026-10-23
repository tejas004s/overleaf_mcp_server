"""MCP Server for LinkedIn Job Search and Human-in-the-Loop Easy Apply Browser Automation."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from .browser_manager import BrowserSessionManager
from .linkedin_automator import LinkedInAutomator
from .profile_store import CandidateProfileStore

mcp = FastMCP(
    "LinkedIn Easy Apply Browser MCP",
    instructions=(
        "Connects to a logged-in Chrome session (via CDP --remote-debugging-port=9222 or persistent profile) "
        "to search LinkedIn jobs, read job descriptions, fill out Easy Apply modals from the user's resume/profile, "
        "and pause at the final 'Submit application' button for human confirmation."
    ),
)

_automator: Optional[LinkedInAutomator] = None


def get_automator() -> LinkedInAutomator:
    global _automator
    if _automator is None:
        _automator = LinkedInAutomator(
            browser_manager=BrowserSessionManager(),
            profile_store=CandidateProfileStore(),
        )
    return _automator


def set_automator(automator: LinkedInAutomator) -> None:
    global _automator
    _automator = automator


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Browser & Profile Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def launch_chrome_debug_session(port: int = 9222) -> str:
    """Launch Google Chrome / Chromium with --remote-debugging-port=9222 so the MCP server can attach to your logged-in LinkedIn session.

    Args:
        port: Chrome Remote Debugging port (default 9222).
    """
    res = get_automator().browser.launch_system_chrome_cdp(port=port)
    return _json(res)


@mcp.tool()
async def check_linkedin_session() -> str:
    """Verify connection to the Chrome browser and check if LinkedIn is logged in."""
    res = await get_automator().check_session_status()
    return _json(res)


@mcp.tool()
def get_candidate_profile() -> str:
    """Read the candidate's saved resume/profile data used to auto-fill LinkedIn Easy Apply forms."""
    store = get_automator().profile
    return _json(
        {
            "profile_path": str(store.profile_path),
            "profile": store.data,
        }
    )


@mcp.tool()
def update_candidate_profile(profile_updates_json: str) -> str:
    """Update the candidate's profile/resume data (contact info, years_of_experience, work_authorization, resume_path, custom_answers).

    Args:
        profile_updates_json: JSON object string containing fields to merge into the candidate profile.
    """
    updates = json.loads(profile_updates_json)
    if not isinstance(updates, dict):
        raise ValueError("profile_updates_json must be a JSON object.")
    updated = get_automator().profile.update(updates)
    return _json(updated)


# ---------------------------------------------------------------------------
# Job Search & Inspection Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_linkedin_jobs(
    keywords: str,
    location: str = "",
    easy_apply_only: bool = True,
    workplace_type: Optional[str] = None,
    date_posted: Optional[str] = None,
    limit: int = 15,
) -> str:
    """Search LinkedIn job listings in the connected browser and return job cards.

    Args:
        keywords: Job title, skills, or keywords (e.g., 'Machine Learning Engineer').
        location: City, state, country, or 'United States' / 'Remote'.
        easy_apply_only: Filter for LinkedIn 'Easy Apply' jobs only (default True).
        workplace_type: Optional filter: 'remote', 'hybrid', or 'onsite'.
        date_posted: Optional recency filter: '24h', 'week', or 'month'.
        limit: Maximum number of job cards to extract (default 15).
    """
    res = await get_automator().search_jobs(
        keywords=keywords,
        location=location,
        easy_apply_only=easy_apply_only,
        workplace_type=workplace_type,
        date_posted=date_posted,
        limit=limit,
    )
    return _json(res)


@mcp.tool()
async def get_linkedin_job_details(job_id_or_url: str) -> str:
    """Open a LinkedIn job listing and extract its full job description, company, title, and Easy Apply availability.

    Args:
        job_id_or_url: LinkedIn Job ID (e.g., '4123456789') or full job URL.
    """
    res = await get_automator().get_job_details(job_id_or_url)
    return _json(res)


# ---------------------------------------------------------------------------
# Easy Apply Modal Automation Tools (Human-in-the-Loop)
# ---------------------------------------------------------------------------


@mcp.tool()
async def start_easy_apply(job_id_or_url: Optional[str] = None) -> str:
    """Click the 'Easy Apply' button on a job listing and return all form fields on the first modal step.

    Args:
        job_id_or_url: Optional Job ID or URL to open first. If omitted, uses the currently open job page.
    """
    res = await get_automator().start_easy_apply(job_id_or_url=job_id_or_url)
    return _json(res)


@mcp.tool()
async def inspect_easy_apply_modal() -> str:
    """Inspect the currently open LinkedIn Easy Apply modal, including fields, profile suggestions, errors, and buttons."""
    res = await get_automator().inspect_easy_apply_modal()
    return _json(res)


@mcp.tool()
async def fill_easy_apply_step(
    answers_json: Optional[str] = None,
    auto_fill_from_profile: bool = True,
    upload_resume: bool = False,
    advance_step: bool = True,
) -> str:
    """Fill the current Easy Apply modal step using your profile and/or custom answers, and advance to Next/Review.
    Never clicks 'Submit application' automatically.

    Args:
        answers_json: Optional JSON object mapping field labels or field_ids to answer values.
        auto_fill_from_profile: Automatically fill recognized fields from candidate profile (default True).
        upload_resume: Upload resume_path from profile if a file input is present (default False).
        advance_step: Click 'Next' or 'Review' after filling (default True).
    """
    answers: Optional[Dict[str, str]] = None
    if answers_json:
        parsed = json.loads(answers_json)
        if not isinstance(parsed, dict):
            raise ValueError("answers_json must decode to a JSON object.")
        answers = {str(k): str(v) for k, v in parsed.items()}

    res = await get_automator().fill_easy_apply_step(
        answers=answers,
        auto_fill_from_profile=auto_fill_from_profile,
        upload_resume=upload_resume,
        advance_step=advance_step,
    )
    return _json(res)


@mcp.tool()
async def autofill_easy_apply_until_review(
    job_id_or_url: Optional[str] = None,
    custom_answers_json: Optional[str] = None,
) -> str:
    """Open Easy Apply and automatically fill all steps using your profile until reaching the final 'Submit application' screen, where it pauses for human confirmation.

    Args:
        job_id_or_url: Optional Job ID or URL to start Easy Apply on.
        custom_answers_json: Optional JSON object with custom question answers for this application.
    """
    custom_answers: Optional[Dict[str, str]] = None
    if custom_answers_json:
        parsed = json.loads(custom_answers_json)
        if isinstance(parsed, dict):
            custom_answers = {str(k): str(v) for k, v in parsed.items()}

    res = await get_automator().autofill_until_review(
        job_id_or_url=job_id_or_url,
        custom_answers=custom_answers,
    )
    return _json(res)


@mcp.tool()
async def submit_easy_apply(confirm_submit: bool = False) -> str:
    """Click the final 'Submit application' button on the LinkedIn Easy Apply modal.
    Requires confirm_submit=True after the user explicitly confirms they want to submit.

    Args:
        confirm_submit: Must be True to click 'Submit application'. If False, returns a confirmation prompt.
    """
    res = await get_automator().submit_easy_apply(confirm_submit=confirm_submit)
    return _json(res)


def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn Easy Apply Browser Automation MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Host for HTTP/SSE transport",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8001")),
        help="Port for HTTP/SSE transport (default 8001)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn

        app = mcp.sse_app() if args.transport == "sse" else mcp.streamable_http_app()
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
