"""Free-Tier Overleaf Browser Sync Client using Playwright and Chrome CDP."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

OVERLEAF_PROJECT_URL_RE = re.compile(r"overleaf\.com/project/([a-fA-F0-9]{16,32})")


class OverleafBrowserClient:
    """Synchronizes Overleaf projects on the Free Tier using a logged-in Chrome browser or share link."""

    def __init__(
        self,
        cdp_url: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
        share_url: Optional[str] = None,
        headless: Optional[bool] = None,
    ) -> None:
        self.cdp_url = (cdp_url or os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222")).strip()
        self.share_url = (share_url or os.getenv("OVERLEAF_SHARE_URL", "")).strip()
        default_profile = Path(
            os.getenv("OVERLEAF_CHROME_PROFILE_DIR", "~/.overleaf_mcp_chrome_profile")
        ).expanduser()
        self.user_data_dir = user_data_dir or default_profile
        self.headless = (
            headless
            if headless is not None
            else os.getenv("OVERLEAF_HEADLESS", "false").lower() in ("1", "true", "yes")
        )

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.connection_type: str = "disconnected"

    @staticmethod
    def find_system_chrome() -> Optional[str]:
        candidates = [
            os.getenv("CHROME_EXECUTABLE_PATH", ""),
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "google-chrome",
            "chromium",
            "chromium-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        for cand in candidates:
            if not cand:
                continue
            resolved = shutil.which(cand) or (cand if Path(cand).exists() else None)
            if resolved:
                return resolved
        return None

    def launch_chrome_debug_session(
        self,
        port: int = 9222,
        target_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Launch system Google Chrome with --remote-debugging-port so the user can view/login to Overleaf."""
        chrome_bin = self.find_system_chrome()
        if not chrome_bin:
            raise FileNotFoundError("Google Chrome or Chromium was not found on this system.")

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        url = target_url or self.share_url or "https://www.overleaf.com/project"
        cmd = [
            chrome_bin,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self.user_data_dir}",
            url,
        ]
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.cdp_url = f"http://127.0.0.1:{port}"
        return {
            "launched": True,
            "executable": chrome_bin,
            "cdp_url": self.cdp_url,
            "opened_url": url,
            "user_data_dir": str(self.user_data_dir),
        }

    async def get_page(self) -> Page:
        """Connect to Chrome CDP on port 9222 or launch persistent Chrome context."""
        if self._page and not self._page.is_closed():
            return self._page

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        # 1. Try existing Chrome over CDP
        if self.cdp_url:
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self.cdp_url, timeout=4000
                )
                self._context = (
                    self._browser.contexts[0]
                    if self._browser.contexts
                    else await self._browser.new_context()
                )
                # Prefer an already-open Overleaf tab if one exists
                for p in self._context.pages:
                    if "overleaf.com" in p.url:
                        self._page = p
                        break
                if not self._page:
                    self._page = (
                        self._context.pages[0]
                        if self._context.pages
                        else await self._context.new_page()
                    )
                self.connection_type = f"cdp ({self.cdp_url})"
                return self._page
            except Exception:
                pass

        # 2. Launch system Chrome with persistent profile
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        chrome_bin = self.find_system_chrome()
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": str(self.user_data_dir),
            "headless": self.headless,
            "viewport": {"width": 1400, "height": 900},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if chrome_bin:
            launch_kwargs["executable_path"] = chrome_bin

        self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        self._page = (
            self._context.pages[0] if self._context.pages else await self._context.new_page()
        )
        self.connection_type = f"persistent ({self.user_data_dir})"
        return self._page

    async def open_project(self, project_id_or_url: Optional[str] = None) -> Dict[str, Any]:
        """Navigate to the Overleaf project or share URL and verify editor state."""
        page = await self.get_page()
        target = (project_id_or_url or self.share_url or "").strip()
        if target and not target.startswith("http"):
            if self.share_url and target in self.share_url:
                target = self.share_url
            else:
                target = f"https://www.overleaf.com/project/{target}"

        if target and target != page.url:
            await page.goto(target, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)

        current_url = page.url
        is_login_page = any(
            x in current_url.lower() for x in ("/login", "/register", "restricted")
        )
        m = OVERLEAF_PROJECT_URL_RE.search(current_url)
        real_project_id = m.group(1) if m else None

        return {
            "current_url": current_url,
            "real_project_id": real_project_id,
            "logged_in_and_open": not is_login_page and "/project/" in current_url,
            "page_title": await page.title(),
        }

    async def sync_to_workspace(
        self,
        workspace_repo_path: Path,
        project_id_or_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download all project files from the open Overleaf browser session into workspace_repo_path."""
        status = await self.open_project(project_id_or_url)
        if not status["logged_in_and_open"]:
            raise RuntimeError(
                f"Overleaf project is not open in an authenticated browser session (current URL: {status['current_url']}). "
                "Please log into Overleaf in the Chrome window first."
            )

        page = await self.get_page()
        real_id = status["real_project_id"]
        workspace_repo_path.mkdir(parents=True, exist_ok=True)

        extracted_files: List[str] = []

        # Method 1: Fetch /project/<real_id>/download/zip inside the authenticated browser page
        if real_id:
            zip_url = f"https://www.overleaf.com/project/{real_id}/download/zip"
            b64_zip = await page.evaluate(
                """
                async (url) => {
                    try {
                        const resp = await fetch(url, { credentials: 'include' });
                        if (!resp.ok) return null;
                        const buf = await resp.arrayBuffer();
                        const bytes = new Uint8Array(buf);
                        let binary = '';
                        for (let i = 0; i < bytes.byteLength; i++) {
                            binary += String.fromCharCode(bytes[i]);
                        }
                        return btoa(binary);
                    } catch (e) {
                        return null;
                    }
                }
                """,
                zip_url,
            )
            if b64_zip:
                raw_bytes = base64.b64decode(b64_zip)
                if raw_bytes.startswith(b"PK"):
                    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                        zf.extractall(workspace_repo_path)
                        extracted_files = zf.namelist()

        # Method 2: Fallback to reading active CodeMirror 6 editor buffer directly
        if not extracted_files:
            editor_text = await self.read_active_editor_text(page)
            if editor_text:
                main_tex = workspace_repo_path / "main.tex"
                main_tex.write_text(editor_text, encoding="utf-8")
                extracted_files = ["main.tex"]

        # Initialize a local git repo in workspace_repo_path so status/diff/history tools work
        if not (workspace_repo_path / ".git").exists():
            subprocess.run(["git", "init"], cwd=str(workspace_repo_path), capture_output=True)
            subprocess.run(
                ["git", "add", "-A"], cwd=str(workspace_repo_path), capture_output=True
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Overleaf Browser Sync",
                    "-c",
                    "user.email=browser@overleaf.local",
                    "commit",
                    "-m",
                    "Initial sync from Overleaf Browser session",
                ],
                cwd=str(workspace_repo_path),
                capture_output=True,
            )

        return {
            "sync_mode": "browser_free_tier",
            "real_project_id": real_id,
            "extracted_files": extracted_files,
            "workspace_path": str(workspace_repo_path),
        }

    async def read_active_editor_text(self, page: Optional[Page] = None) -> str:
        """Read the full LaTeX source from the currently open Overleaf CodeMirror editor."""
        p = page or await self.get_page()
        await p.wait_for_selector(".cm-content, .ace_editor", timeout=15000)
        return await p.evaluate(
            """
            () => {
                const cmContent = document.querySelector('.cm-content');
                if (cmContent && cmContent.cmView && cmContent.cmView.view) {
                    return cmContent.cmView.view.state.doc.toString();
                }
                if (cmContent) {
                    return Array.from(cmContent.querySelectorAll('.cm-line'))
                        .map(line => line.innerText.replace(/\\u200b/g, ''))
                        .join('\\n');
                }
                return '';
            }
            """
        )

    async def write_file_in_browser(
        self,
        file_path: str,
        new_content: str,
        project_id_or_url: Optional[str] = None,
        recompile: bool = True,
    ) -> Dict[str, Any]:
        """Select a file in the Overleaf file tree, update its CodeMirror editor content, and trigger Recompile."""
        status = await self.open_project(project_id_or_url)
        if not status["logged_in_and_open"]:
            raise RuntimeError(
                "Overleaf project is not open in an authenticated browser window. "
                "Call launch_overleaf_browser first and log into Overleaf."
            )

        page = await self.get_page()
        filename = Path(file_path).name

        # Click the target file in the Overleaf file tree
        await page.evaluate(
            """
            (targetName) => {
                const items = Array.from(document.querySelectorAll(
                    '.file-tree-list li, [role="treeitem"], .entity-name'
                ));
                for (const item of items) {
                    const txt = (item.innerText || '').trim().split('\\n')[0].trim();
                    if (txt === targetName) {
                        const clickable = item.querySelector('a, button, .entity-name') || item;
                        clickable.click();
                        return true;
                    }
                }
                return false;
            }
            """,
            filename,
        )
        await page.wait_for_timeout(700)

        # Update the CodeMirror 6 document buffer (or fallback to select-all + insertText)
        updated_via_cm_api = await page.evaluate(
            """
            (text) => {
                const cmContent = document.querySelector('.cm-content');
                if (cmContent && cmContent.cmView && cmContent.cmView.view) {
                    const view = cmContent.cmView.view;
                    view.dispatch({
                        changes: { from: 0, to: view.state.doc.length, insert: text }
                    });
                    return true;
                }
                return false;
            }
            """,
            new_content,
        )

        if not updated_via_cm_api:
            cm_loc = page.locator(".cm-content").first
            await cm_loc.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.insert_text(new_content)

        if recompile:
            await page.keyboard.press("Control+Enter")
            await page.wait_for_timeout(500)

        return {
            "pushed_via_browser": True,
            "file_path": file_path,
            "recompiled": recompile,
        }


def run_sync(coro: Any) -> Any:
    """Run an async browser operation from synchronous code."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
