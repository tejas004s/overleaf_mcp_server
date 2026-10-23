"""Configuration and project registry for the Overleaf MCP Server."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()

PROJECT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
OVERLEAF_URL_PROJECT_RE = re.compile(r"overleaf\.com/project/([a-fA-F0-9]+)")


def extract_project_id(id_or_url: str) -> str:
    """Extract an Overleaf project ID from either a raw ID or an Overleaf URL."""
    value = id_or_url.strip()
    match = OVERLEAF_URL_PROJECT_RE.search(value)
    if match:
        return match.group(1)
    if value.endswith(".git") and "git.overleaf.com/" in value:
        return value.rsplit("/", 1)[-1][:-4]
    if "git.overleaf.com/" in value:
        return value.rstrip("/").rsplit("/", 1)[-1]
    return value


def parse_projects_env(raw: str) -> Dict[str, str]:
    """Parse OVERLEAF_PROJECTS from JSON or comma-separated alias=project_id pairs."""
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k).strip(): extract_project_id(str(v)) for k, v in data.items()}
        except json.JSONDecodeError:
            pass

    projects: Dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            alias, pid = item.split("=", 1)
            projects[alias.strip()] = extract_project_id(pid.strip())
        else:
            pid = extract_project_id(item)
            projects[pid] = pid
    return projects


@dataclass
class OverleafConfig:
    """Runtime configuration for Overleaf Git Bridge operations."""

    git_token: str = field(default_factory=lambda: os.getenv("OVERLEAF_GIT_TOKEN", "").strip())
    default_project_id: str = field(
        default_factory=lambda: extract_project_id(os.getenv("OVERLEAF_PROJECT_ID", ""))
    )
    git_base_url: str = field(
        default_factory=lambda: os.getenv("OVERLEAF_GIT_BASE_URL", "https://git.overleaf.com")
        .strip()
        .rstrip("/")
    )
    workspace_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("OVERLEAF_WORKSPACE_DIR", "./.overleaf_workspace")
        ).expanduser().resolve()
    )
    author_name: str = field(
        default_factory=lambda: os.getenv("OVERLEAF_GIT_AUTHOR_NAME", "Overleaf MCP Assistant").strip()
    )
    author_email: str = field(
        default_factory=lambda: os.getenv("OVERLEAF_GIT_AUTHOR_EMAIL", "mcp@overleaf.local").strip()
    )
    mcp_api_key: str = field(default_factory=lambda: os.getenv("MCP_API_KEY", "").strip())
    projects: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        env_projects = parse_projects_env(os.getenv("OVERLEAF_PROJECTS", ""))
        saved_projects = self._load_saved_projects()
        merged = {**saved_projects, **env_projects}
        if self.default_project_id and "default" not in merged:
            merged["default"] = self.default_project_id
        self.projects.update(merged)

    @property
    def registry_file(self) -> Path:
        return self.workspace_dir / "projects.json"

    def _load_saved_projects(self) -> Dict[str, str]:
        if not self.registry_file.exists():
            return {}
        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def save_projects(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            json.dumps(self.projects, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def register_project(
        self, alias: str, project_id_or_url: str, set_default: bool = False
    ) -> str:
        """Register an alias for an Overleaf project ID or Git URL."""
        alias = alias.strip()
        if not alias:
            raise ValueError("Project alias cannot be empty.")
        resolved = extract_project_id(project_id_or_url)
        self.projects[alias] = resolved
        if set_default or not self.default_project_id:
            self.default_project_id = resolved
            self.projects["default"] = resolved
        self.save_projects()
        return resolved

    def resolve_project_id(self, project: Optional[str] = None) -> str:
        """Resolve an alias, project ID, or fallback to default_project_id."""
        if project:
            project = project.strip()
            if project in self.projects:
                return self.projects[project]
            return extract_project_id(project)

        if self.default_project_id:
            return self.default_project_id

        if len(self.projects) == 1:
            return next(iter(self.projects.values()))

        raise ValueError(
            "No Overleaf project specified and OVERLEAF_PROJECT_ID is not set. "
            "Pass a project ID/alias or register one with register_project."
        )

    def build_git_remote_url(self, project_id_or_url: str) -> str:
        """Build the authenticated Git remote URL for Overleaf or local/custom Git remotes."""
        target = project_id_or_url.strip()

        # Support local paths or file:// URLs for testing / local bare repos
        if target.startswith(("file://", "/")) or Path(target).exists():
            return target

        # If full URL was provided, inject token if needed
        if target.startswith(("http://", "https://")):
            parsed = urlparse(target)
            if self.git_token and "@" not in parsed.netloc:
                netloc = f"git:{self.git_token}@{parsed.netloc}"
                return urlunparse(parsed._replace(netloc=netloc))
            return target

        # Standard Overleaf Project ID -> https://git:<token>@git.overleaf.com/<project_id>
        parsed_base = urlparse(self.git_base_url)
        if parsed_base.scheme in ("http", "https"):
            if not self.git_token:
                raise ValueError(
                    "OVERLEAF_GIT_TOKEN is not configured. Generate a Git token in Overleaf "
                    "(Account Settings -> Git Integration) and set OVERLEAF_GIT_TOKEN."
                )
            netloc = f"git:{self.git_token}@{parsed_base.netloc}"
            path = f"{parsed_base.path.rstrip('/')}/{target}"
            return urlunparse(parsed_base._replace(netloc=netloc, path=path))

        # Local base path fallback
        return f"{self.git_base_url.rstrip('/')}/{target}"

    def project_dir_name(self, resolved_target: str) -> str:
        """Return a safe directory name inside workspace_dir for the project."""
        clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", Path(resolved_target).stem or resolved_target)
        return clean.strip("_") or "project"

    def redact_secrets(self, text: str) -> str:
        """Redact git token from any logs or error messages."""
        if not text:
            return text
        redacted = text
        if self.git_token:
            redacted = redacted.replace(self.git_token, "***REDACTED***")
        redacted = re.sub(r"git:[^@\s]+@", "git:***REDACTED***@", redacted)
        return redacted
