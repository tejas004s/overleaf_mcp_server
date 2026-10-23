"""Git Bridge client for cloning, syncing, editing, and pushing Overleaf projects."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import OverleafConfig


class OverleafGitError(RuntimeError):
    """Raised when a Git Bridge operation fails."""


@dataclass
class GitCommandResult:
    returncode: int
    stdout: str
    stderr: str


class OverleafGitClient:
    """Manages local Git checkouts synchronized with Overleaf's Git Bridge."""

    def __init__(self, config: Optional[OverleafConfig] = None) -> None:
        self.config = config or OverleafConfig()

    def _run_git(
        self,
        args: List[str],
        cwd: Optional[Path] = None,
        check: bool = True,
        timeout: int = 90,
    ) -> GitCommandResult:
        env_cmd = [
            "git",
            "-c",
            f"user.name={self.config.author_name}",
            "-c",
            f"user.email={self.config.author_email}",
            "-c",
            "credential.helper=",
            *args,
        ]
        try:
            proc = subprocess.run(
                env_cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OverleafGitError(
                f"Git command timed out after {timeout}s: {' '.join(args[:2])}"
            ) from exc

        stdout = self.config.redact_secrets(proc.stdout.strip())
        stderr = self.config.redact_secrets(proc.stderr.strip())

        if check and proc.returncode != 0:
            detail = stderr or stdout or f"exit code {proc.returncode}"
            raise OverleafGitError(f"Git operation failed ({' '.join(args[:2])}): {detail}")

        return GitCommandResult(proc.returncode, stdout, stderr)

    def get_repo_path(self, project: Optional[str] = None) -> Path:
        """Return the local directory path for the specified project."""
        resolved = self.config.resolve_project_id(project)
        dir_name = self.config.project_dir_name(resolved)
        return self.config.workspace_dir / dir_name

    def ensure_repo(self, project: Optional[str] = None, auto_pull: bool = True) -> Path:
        """Ensure the project is cloned locally and optionally pull latest changes."""
        resolved = self.config.resolve_project_id(project)
        repo_path = self.get_repo_path(project)
        remote_url = self.config.build_git_remote_url(resolved)

        if not (repo_path / ".git").exists():
            repo_path.parent.mkdir(parents=True, exist_ok=True)
            self._run_git(["clone", remote_url, str(repo_path)])
        else:
            # Ensure remote URL stays up-to-date with current token
            self._run_git(["remote", "set-url", "origin", remote_url], cwd=repo_path)
            if auto_pull:
                self.pull(project=project, repo_path=repo_path)

        return repo_path

    def pull(self, project: Optional[str] = None, repo_path: Optional[Path] = None) -> str:
        """Pull latest changes from Overleaf remote."""
        repo = repo_path or self.ensure_repo(project, auto_pull=False)
        # Check if there are uncommitted local modifications before pulling
        status = self._run_git(["status", "--porcelain"], cwd=repo, check=False)
        has_dirty = bool(status.stdout.strip())

        if has_dirty:
            self._run_git(["stash", "push", "-u", "-m", "overleaf-mcp-autostash"], cwd=repo, check=False)

        try:
            res = self._run_git(["pull", "--rebase", "origin"], cwd=repo, check=False)
            if res.returncode != 0:
                # Abort rebase if conflict and report clearly
                self._run_git(["rebase", "--abort"], cwd=repo, check=False)
                raise OverleafGitError(
                    f"Failed to pull latest changes from Overleaf: {res.stderr or res.stdout}"
                )
            return res.stdout or "Already up to date."
        finally:
            if has_dirty:
                self._run_git(["stash", "pop"], cwd=repo, check=False)

    def resolve_safe_file(self, repo_path: Path, relative_path: str) -> Path:
        """Resolve a file path inside repo_path and prevent path traversal."""
        cleaned = relative_path.lstrip("/").strip()
        if not cleaned:
            raise ValueError("File path cannot be empty.")
        target = (repo_path / cleaned).resolve()
        repo_resolved = repo_path.resolve()
        if target != repo_resolved and repo_resolved not in target.parents:
            raise ValueError(f"Invalid path '{relative_path}': path traversal outside project root.")
        if ".git" in target.relative_to(repo_resolved).parts:
            raise ValueError("Cannot access internal .git directory.")
        return target

    def list_files(
        self,
        project: Optional[str] = None,
        extension_filter: Optional[str] = None,
        auto_pull: bool = True,
    ) -> List[Dict[str, Any]]:
        """List all files in the Overleaf project."""
        repo = self.ensure_repo(project, auto_pull=auto_pull)
        files: List[Dict[str, Any]] = []
        for path in sorted(repo.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(repo).parts
            if ".git" in rel_parts:
                continue
            if extension_filter and not path.name.endswith(extension_filter):
                continue
            stat = path.stat()
            files.append(
                {
                    "path": str(path.relative_to(repo)),
                    "size_bytes": stat.st_size,
                    "extension": path.suffix,
                }
            )
        return files

    def read_file(
        self,
        file_path: str,
        project: Optional[str] = None,
        auto_pull: bool = True,
    ) -> str:
        """Read a text file from the Overleaf project."""
        repo = self.ensure_repo(project, auto_pull=auto_pull)
        target = self.resolve_safe_file(repo, file_path)
        if not target.exists():
            raise FileNotFoundError(f"File '{file_path}' not found in project.")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_file(
        self,
        file_path: str,
        content: str,
        project: Optional[str] = None,
        commit_message: Optional[str] = None,
        auto_push: bool = True,
    ) -> Dict[str, Any]:
        """Write or overwrite a file in the project, and optionally commit & push to Overleaf."""
        repo = self.ensure_repo(project, auto_pull=True)
        target = self.resolve_safe_file(repo, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        result: Dict[str, Any] = {
            "file_path": str(target.relative_to(repo)),
            "bytes_written": len(content.encode("utf-8")),
            "pushed": False,
        }
        if auto_push:
            msg = commit_message or f"Update {target.relative_to(repo)} via Overleaf MCP"
            sync_info = self.commit_and_push(message=msg, project=project, repo_path=repo)
            result.update(sync_info)
        return result

    def delete_file(
        self,
        file_path: str,
        project: Optional[str] = None,
        commit_message: Optional[str] = None,
        auto_push: bool = True,
    ) -> Dict[str, Any]:
        """Delete a file from the Overleaf project and optionally push the deletion."""
        repo = self.ensure_repo(project, auto_pull=True)
        target = self.resolve_safe_file(repo, file_path)
        if not target.exists():
            raise FileNotFoundError(f"File '{file_path}' does not exist.")
        rel = str(target.relative_to(repo))
        target.unlink()

        result: Dict[str, Any] = {"deleted_file": rel, "pushed": False}
        if auto_push:
            msg = commit_message or f"Delete {rel} via Overleaf MCP"
            sync_info = self.commit_and_push(message=msg, project=project, repo_path=repo)
            result.update(sync_info)
        return result

    def commit_and_push(
        self,
        message: str = "Update from Overleaf MCP",
        project: Optional[str] = None,
        repo_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Stage all changes, commit, and push back to Overleaf Git Bridge."""
        repo = repo_path or self.ensure_repo(project, auto_pull=False)
        self._run_git(["add", "-A"], cwd=repo)

        status = self._run_git(["status", "--porcelain"], cwd=repo)
        if not status.stdout.strip():
            return {
                "committed": False,
                "pushed": False,
                "status": "No changes to commit.",
            }

        self._run_git(["commit", "-m", message], cwd=repo)
        commit_hash = self._run_git(["rev-parse", "--short", "HEAD"], cwd=repo).stdout

        # Push; if rejected due to concurrent Overleaf edits, pull --rebase and retry once
        push_res = self._run_git(["push", "origin", "HEAD"], cwd=repo, check=False)
        if push_res.returncode != 0:
            self._run_git(["pull", "--rebase", "origin"], cwd=repo)
            self._run_git(["push", "origin", "HEAD"], cwd=repo)

        return {
            "committed": True,
            "pushed": True,
            "commit": commit_hash,
            "message": message,
        }

    def status_and_diff(self, project: Optional[str] = None) -> Dict[str, Any]:
        """Return current git status, branch info, and unstaged/staged diff."""
        repo = self.ensure_repo(project, auto_pull=False)
        status = self._run_git(["status", "-sb"], cwd=repo).stdout
        diff = self._run_git(["diff", "HEAD"], cwd=repo, check=False).stdout
        return {
            "status": status,
            "diff": diff,
        }

    def get_history(self, project: Optional[str] = None, limit: int = 10) -> List[Dict[str, str]]:
        """Return recent Git commits in the Overleaf project."""
        repo = self.ensure_repo(project, auto_pull=True)
        fmt = "%h%x1f%an%x1f%ad%x1f%s"
        res = self._run_git(
            ["log", f"-n{max(1, min(limit, 50))}", "--date=iso", f"--pretty=format:{fmt}"],
            cwd=repo,
            check=False,
        )
        commits: List[Dict[str, str]] = []
        for line in res.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append(
                    {
                        "commit": parts[0],
                        "author": parts[1],
                        "date": parts[2],
                        "subject": parts[3],
                    }
                )
        return commits
