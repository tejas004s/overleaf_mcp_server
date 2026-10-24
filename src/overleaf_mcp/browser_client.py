"""Playwright Browser Automation for Overleaf (Free Tier & Cloud Deployment Ready).

Supports:
1. OVERLEAF_SESSION_COOKIE (raw cookie string for zero-install cloud deployment)
2. OVERLEAF_STORAGE_STATE_B64 / storage_state.json (exported via setup_auth.py + export_session.py)
3. Chrome Remote Debugging (CDP --remote-debugging-port=9222)
4. Persistent local Chromium profile (./browser_data)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_PROFILE_DIR = BASE_DIR / "browser_data"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"

OVERLEAF_PROFILE_DIR = Path(os.getenv("OVERLEAF_PROFILE_DIR", str(DEFAULT_PROFILE_DIR))).expanduser()
OVERLEAF_OUTPUT_DIR = Path(os.getenv("OVERLEAF_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))).expanduser()
HEADLESS = os.getenv("OVERLEAF_HEADLESS", "true").lower() in ("true", "1", "yes")

IS_CLOUD = bool(os.getenv("PORT") or os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER"))
SERVER_HOST = "0.0.0.0" if IS_CLOUD else os.getenv("MCP_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("PORT", os.getenv("MCP_PORT", "8000")))
TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")

_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
_explicit_url = os.getenv("PUBLIC_URL", "")
if _explicit_url:
    PUBLIC_URL = _explicit_url.rstrip("/")
elif _railway_domain:
    PUBLIC_URL = f"https://{_railway_domain}"
elif not IS_CLOUD:
    PUBLIC_URL = f"http://127.0.0.1:{SERVER_PORT}"
else:
    PUBLIC_URL = ""

OVERLEAF_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
OVERLEAF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class OverleafBrowserClient:
    """Manages Playwright browser automation for Overleaf with cloud & local persistent authentication."""

    def __init__(
        self,
        cdp_url: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
        share_url: Optional[str] = None,
        headless: Optional[bool] = None,
    ) -> None:
        self.cdp_url = (cdp_url or os.getenv("CHROME_CDP_URL", "")).strip()
        self.share_url = (share_url or os.getenv("OVERLEAF_SHARE_URL", "")).strip()
        self.user_data_dir = user_data_dir or OVERLEAF_PROFILE_DIR
        self.output_dir = OVERLEAF_OUTPUT_DIR
        self.headless = headless if headless is not None else HEADLESS

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._current_project_id: Optional[str] = None
        self._lock = asyncio.Lock()
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

    def _sanitize_storage_state(self, state_file_path: Path) -> Dict[str, Any]:
        """Sanitize storage_state.json for Playwright (Overleaf cookies + valid sameSite/secure)."""
        raw = json.loads(state_file_path.read_text(encoding="utf-8"))
        valid_same_sites = {"Strict", "Lax", "None"}
        sanitized_cookies: List[Dict[str, Any]] = []

        for cookie in raw.get("cookies", []):
            domain = cookie.get("domain", "")
            if "overleaf.com" not in domain:
                continue
            if not cookie.get("name") or cookie.get("value") is None:
                continue
            same_site = cookie.get("sameSite", "Lax")
            if same_site not in valid_same_sites:
                same_site = "Lax"
            if same_site == "None":
                cookie["secure"] = True
            cookie["sameSite"] = same_site
            if not cookie.get("path"):
                cookie["path"] = "/"
            sanitized_cookies.append(cookie)

        return {
            "cookies": sanitized_cookies,
            "origins": raw.get("origins", []),
        }

    async def _ensure_browser(self) -> Page:
        """Initialize or return existing browser session supporting Railway/Render cloud state or local profile."""
        if self._page and not self._page.is_closed():
            return self._page

        if not self._playwright:
            self._playwright = await async_playwright().start()

        chromium_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ]

        # 0. Try Chrome CDP if explicitly configured and reachable
        if self.cdp_url:
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self.cdp_url, timeout=3000
                )
                self._context = (
                    self._browser.contexts[0]
                    if self._browser.contexts
                    else await self._browser.new_context(accept_downloads=True)
                )
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

        chrome_bin = self.find_system_chrome()
        launch_kwargs: Dict[str, Any] = {
            "headless": self.headless,
            "args": chromium_args,
        }
        # Use system Chrome only if Playwright's bundled chromium isn't installed
        try:
            pw_exec = self._playwright.chromium.executable_path
            if not Path(pw_exec).exists() and chrome_bin:
                launch_kwargs["executable_path"] = chrome_bin
        except Exception:
            if chrome_bin:
                launch_kwargs["executable_path"] = chrome_bin

        # 1. Check OVERLEAF_SESSION_COOKIE (Zero-install cloud deployment)
        session_cookie = os.getenv("OVERLEAF_SESSION_COOKIE", "").strip()
        if session_cookie:
            browser_instance = await self._playwright.chromium.launch(**launch_kwargs)
            self._context = await browser_instance.new_context(
                viewport={"width": 1440, "height": 900},
                accept_downloads=True,
            )
            raw = session_cookie.strip("\"' \n\r\t")
            parsed_cookies = []
            parts = [p.strip() for p in raw.split(";") if p.strip()]
            for part in parts:
                if "=" in part:
                    k, v = part.split("=", 1)
                    k, v = k.strip(), v.strip("\"' \n\r\t")
                    if k and v:
                        parsed_cookies.append(
                            {"name": k, "value": v, "url": "https://www.overleaf.com"}
                        )
                else:
                    v = part.strip("\"' \n\r\t")
                    if v:
                        parsed_cookies.append(
                            {"name": "overleaf_session2", "value": v, "url": "https://www.overleaf.com"}
                        )
                        parsed_cookies.append(
                            {"name": "overleaf_session", "value": v, "url": "https://www.overleaf.com"}
                        )
            if parsed_cookies:
                await self._context.add_cookies(parsed_cookies)
            self._page = await self._context.new_page()
            self.connection_type = "session_cookie"
            return self._page

        # 2. Check OVERLEAF_STORAGE_STATE_B64 or storage_state.json (Railway / Render / Docker)
        state_file_path = BASE_DIR / "storage_state.json"
        b64_env = os.getenv("OVERLEAF_STORAGE_STATE_B64", "").strip()
        if b64_env and not state_file_path.exists():
            try:
                decoded = base64.b64decode(b64_env).decode("utf-8")
                state_file_path.write_text(decoded, encoding="utf-8")
            except Exception as exc:
                print(f"Warning: Failed to decode OVERLEAF_STORAGE_STATE_B64: {exc}")

        if state_file_path.exists():
            browser_instance = await self._playwright.chromium.launch(**launch_kwargs)
            sanitized_state = self._sanitize_storage_state(state_file_path)
            self._context = await browser_instance.new_context(
                storage_state=sanitized_state,
                viewport={"width": 1440, "height": 900},
                accept_downloads=True,
            )
            self._page = await self._context.new_page()
            self.connection_type = f"storage_state ({state_file_path})"
            return self._page

        # 3. Fallback to persistent profile directory (./browser_data)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
            **launch_kwargs,
        )
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self.connection_type = f"persistent ({self.user_data_dir})"
        return self._page

    async def get_page(self) -> Page:
        return await self._ensure_browser()

    def launch_chrome_debug_session(
        self,
        port: int = 9222,
        target_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Launch system Google Chrome with --remote-debugging-port for interactive login."""
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

    async def check_auth_status(self) -> Dict[str, Any]:
        """Check whether the browser session is authenticated on Overleaf."""
        async with self._lock:
            try:
                page = await self._ensure_browser()
                target = self.share_url or "https://www.overleaf.com/project"
                await page.goto(target, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2)
                url = page.url
                if "/login" in url or "/register" in url:
                    return {
                        "authenticated": False,
                        "url": url,
                        "connection_type": self.connection_type,
                        "message": (
                            "User is not logged in. Run `python3 setup_auth.py` locally, or set "
                            "OVERLEAF_STORAGE_STATE_B64 / OVERLEAF_SESSION_COOKIE in cloud variables."
                        ),
                    }
                return {
                    "authenticated": True,
                    "url": url,
                    "connection_type": self.connection_type,
                    "message": "Authenticated successfully with Overleaf.",
                }
            except Exception as exc:
                return {
                    "authenticated": False,
                    "error": str(exc),
                    "message": f"Browser navigation error: {exc}",
                }

    async def open_project(self, project_url_or_id: Optional[str] = None) -> Dict[str, Any]:
        """Navigate to an Overleaf project by full URL, share link, or 24-character Project ID."""
        async with self._lock:
            page = await self._ensure_browser()
            raw_target = (
                project_url_or_id
                or self.share_url
                or os.getenv("OVERLEAF_PROJECT_ID", "")
            ).strip()

            if not raw_target:
                raise ValueError("Provide a project_url_or_id or set OVERLEAF_PROJECT_ID / OVERLEAF_SHARE_URL.")

            # Preserve full share URLs (/share#...) or full http URLs
            if raw_target.startswith(("http://", "https://")):
                target_url = raw_target
            elif self.share_url and raw_target in self.share_url:
                target_url = self.share_url
            else:
                match = re.search(r"([0-9a-f]{24}|[0-9a-zA-Z_-]{16,})", raw_target)
                proj_id = match.group(1) if match else raw_target
                target_url = f"https://www.overleaf.com/project/{proj_id}"

            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

            if "/login" in page.url:
                return {
                    "success": False,
                    "logged_in_and_open": False,
                    "current_url": page.url,
                    "error": "Redirected to login. Run `python3 setup_auth.py` once to authenticate.",
                }

            try:
                await page.wait_for_selector(
                    ".cm-content, .cm-editor, .ace_editor, [role='region'][aria-label*='editor' i]",
                    timeout=20000,
                )
            except Exception:
                pass

            await asyncio.sleep(1.5)
            title = await page.title()

            current_match = re.search(r"/project/([0-9a-f]{24}|[0-9a-zA-Z_-]+)", page.url)
            if current_match:
                self._current_project_id = current_match.group(1)

            current_file = await self._get_current_filename(page)
            return {
                "success": True,
                "logged_in_and_open": True,
                "url": page.url,
                "current_url": page.url,
                "project_title": title,
                "page_title": title,
                "current_file": current_file,
                "project_id": self._current_project_id,
                "real_project_id": self._current_project_id,
            }

    async def _get_current_filename(self, page: Page) -> str:
        try:
            filename = await page.evaluate(
                """
                () => {
                    const activeTreeItem = document.querySelector('.file-tree-item.selected, [role="treeitem"][aria-selected="true"]');
                    if (activeTreeItem) {
                        const match = activeTreeItem.innerText.match(/[a-zA-Z0-9_.-]+\\.[a-zA-Z0-9]+/);
                        if (match) return match[0];
                        return activeTreeItem.innerText.trim();
                    }
                    const activeTab = document.querySelector('.editor-tabs .active, [data-testid="file-name"]');
                    if (activeTab) {
                        return activeTab.innerText.trim();
                    }
                    return 'main.tex';
                }
                """
            )
            return filename or "main.tex"
        except Exception:
            return "main.tex"

    async def list_files(self) -> Dict[str, Any]:
        """List files visible in the Overleaf project file tree."""
        async with self._lock:
            page = await self._ensure_browser()
            try:
                files = await page.evaluate(
                    """
                    () => {
                        const fileTree = document.querySelector('.file-tree, [aria-label*="File tree" i]');
                        const scope = fileTree || document;
                        const items = Array.from(scope.querySelectorAll('.file-tree-item, .entity-name, [role="treeitem"]'));
                        const names = [];
                        for (const el of items) {
                            const raw = (el.innerText || el.getAttribute('aria-label') || '').trim();
                            const match = raw.match(/[a-zA-Z0-9_.-]+\\.(tex|cls|bib|sty|pdf|png|jpg|jpeg)/i);
                            if (match && !names.includes(match[0])) {
                                names.push(match[0]);
                            }
                        }
                        if (names.length === 0) {
                            names.push('main.tex');
                        }
                        return names;
                    }
                    """
                )
                return {"success": True, "files": files}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    async def open_file(self, filename: str) -> Dict[str, Any]:
        """Click a file in the Overleaf project file tree to open it in the editor."""
        async with self._lock:
            page = await self._ensure_browser()
            try:
                selector = f"[role='treeitem']:has-text('{filename}'), .file-tree-item:has-text('{filename}')"
                el = await page.query_selector(selector)
                if not el:
                    items = await page.query_selector_all("[role='treeitem'], .file-tree-item")
                    for item in items:
                        text = (await item.inner_text()).strip()
                        if filename.lower() in text.lower():
                            el = item
                            break

                if el:
                    await el.click()
                    await asyncio.sleep(1.5)
                    return {"success": True, "message": f"Opened file '{filename}'"}
                return {"success": False, "error": f"File '{filename}' not found in file tree."}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    async def get_latex_content(self) -> Dict[str, Any]:
        """Retrieve the full LaTeX content from the active Overleaf CodeMirror 6 / Ace editor."""
        async with self._lock:
            page = await self._ensure_browser()
            try:
                result = await page.evaluate(
                    """
                    () => {
                        const cmContent = document.querySelector('.cm-content');
                        if (cmContent && cmContent.cmView && cmContent.cmView.view) {
                            const view = cmContent.cmView.view;
                            if (view.state && view.state.doc) {
                                return {
                                    content: view.state.doc.toString(),
                                    lines: view.state.doc.lines,
                                    engine: 'codemirror6-view'
                                };
                            }
                        }

                        const cmEditorEl = document.querySelector('.cm-editor');
                        if (cmEditorEl && cmEditorEl.cmView && cmEditorEl.cmView.view) {
                            const view = cmEditorEl.cmView.view;
                            if (view.state && view.state.doc) {
                                return {
                                    content: view.state.doc.toString(),
                                    lines: view.state.doc.lines,
                                    engine: 'codemirror6-editor-view'
                                };
                            }
                        }

                        const aceEl = document.querySelector('.ace_editor');
                        if (aceEl && window.ace) {
                            try {
                                const editor = window.ace.edit(aceEl);
                                const val = editor.getValue();
                                return {
                                    content: val,
                                    lines: val.split('\\n').length,
                                    engine: 'ace'
                                };
                            } catch (e) {}
                        }

                        if (cmContent) {
                            const lines = Array.from(cmContent.querySelectorAll('.cm-line'));
                            if (lines.length > 0) {
                                const txt = lines.map(l => l.innerText).join('\\n');
                                return {
                                    content: txt,
                                    lines: lines.length,
                                    engine: 'codemirror6-dom-lines'
                                };
                            }
                            return {
                                content: cmContent.innerText,
                                lines: cmContent.innerText.split('\\n').length,
                                engine: 'codemirror6-innertext'
                            };
                        }

                        return { content: null, lines: 0, engine: 'not-found' };
                    }
                    """
                )

                if result.get("content") is not None:
                    return {
                        "success": True,
                        "latex": result["content"],
                        "engine": result["engine"],
                        "line_count": result.get("lines", len(result["content"].splitlines())),
                    }
                return {
                    "success": False,
                    "error": "Could not extract editor content. Ensure an editable LaTeX file is open.",
                }
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    async def set_latex_content(self, latex_code: str) -> Dict[str, Any]:
        """Replace the active Overleaf editor buffer with new LaTeX code via CodeMirror 6 view.dispatch."""
        async with self._lock:
            page = await self._ensure_browser()
            try:
                update_result = await page.evaluate(
                    """
                    (newContent) => {
                        const cmContent = document.querySelector('.cm-content');
                        if (cmContent && cmContent.cmView && cmContent.cmView.view) {
                            const view = cmContent.cmView.view;
                            const currentLen = view.state.doc.length;
                            view.dispatch({
                                changes: { from: 0, to: currentLen, insert: newContent }
                            });
                            return { success: true, method: 'cm6_content_view_dispatch' };
                        }

                        const cmEditorEl = document.querySelector('.cm-editor');
                        if (cmEditorEl && cmEditorEl.cmView && cmEditorEl.cmView.view) {
                            const view = cmEditorEl.cmView.view;
                            const currentLen = view.state.doc.length;
                            view.dispatch({
                                changes: { from: 0, to: currentLen, insert: newContent }
                            });
                            return { success: true, method: 'cm6_editor_view_dispatch' };
                        }

                        const aceEl = document.querySelector('.ace_editor');
                        if (aceEl && window.ace) {
                            try {
                                const editor = window.ace.edit(aceEl);
                                editor.setValue(newContent, -1);
                                return { success: true, method: 'ace_setValue' };
                            } catch (e) {}
                        }

                        return { success: false, method: 'js_injection_failed' };
                    }
                    """,
                    latex_code,
                )

                if update_result.get("success"):
                    await asyncio.sleep(2)
                    return {
                        "success": True,
                        "method": update_result.get("method"),
                        "message": "LaTeX content updated successfully.",
                    }

                editor_sel = ".cm-content, .cm-editor, .ace_editor"
                await page.click(editor_sel)
                is_mac = "mac" in (await page.evaluate("navigator.platform")).lower()
                cmd_key = "Meta" if is_mac else "Control"
                await page.keyboard.press(f"{cmd_key}+A")
                await asyncio.sleep(0.3)
                await page.keyboard.insert_text(latex_code)
                await asyncio.sleep(2)

                return {
                    "success": True,
                    "method": "keyboard_insert_text",
                    "message": "LaTeX content replaced via editor typing.",
                }
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    async def recompile(self, timeout_seconds: int = 40) -> Dict[str, Any]:
        """Trigger Overleaf Recompile, wait for completion, and collect any compilation errors."""
        async with self._lock:
            page = await self._ensure_browser()
            try:
                clicked = False
                try:
                    btn = page.locator(
                        "button:has-text('Recompile'), .btn-recompile, [aria-label*='Recompile' i]"
                    ).first
                    if await btn.is_visible(timeout=3000):
                        await btn.click()
                        clicked = True
                except Exception:
                    pass

                if not clicked:
                    is_mac = "mac" in (await page.evaluate("navigator.platform")).lower()
                    cmd_key = "Meta" if is_mac else "Control"
                    await page.keyboard.press(f"{cmd_key}+Enter")

                await asyncio.sleep(1.5)
                start_time = time.time()
                compiling = True

                while compiling and (time.time() - start_time < timeout_seconds):
                    await asyncio.sleep(1)
                    compiling = await page.evaluate(
                        """
                        () => {
                            const buttons = Array.from(document.querySelectorAll('button, .btn'));
                            const btn = buttons.find(b => {
                                const t = (b.innerText || b.getAttribute('aria-label') || '').toLowerCase();
                                return t.includes('recompile') || b.classList.contains('btn-recompile');
                            });
                            if (btn && (btn.disabled || btn.classList.contains('compiling') || btn.innerText.toLowerCase().includes('compiling'))) {
                                return true;
                            }
                            const spinner = document.querySelector('.fa-spinner, .loading-spinner, [aria-label*="compiling" i]');
                            return !!spinner;
                        }
                        """
                    )

                compile_info = await page.evaluate(
                    """
                    () => {
                        const errorBadge = document.querySelector('.btn-recompile-error, .badge-danger, [aria-label*="error" i], [aria-label*="errors" i]');
                        const errorCount = errorBadge ? errorBadge.innerText.trim() : null;

                        const logErrors = Array.from(document.querySelectorAll('.log-entry-message, .error-message, .alert-danger'))
                            .map(el => el.innerText.trim())
                            .filter(Boolean);

                        const hasPdfViewer = !!document.querySelector('.pdf-viewer, #pdf-viewer, iframe[src*="pdf"], canvas.pdf-page');

                        return {
                            has_pdf: hasPdfViewer,
                            error_badge: errorCount,
                            log_errors: logErrors.slice(0, 5)
                        };
                    }
                    """
                )

                has_errors = bool(
                    compile_info.get("log_errors")
                    or (
                        compile_info.get("error_badge")
                        and "error" in str(compile_info.get("error_badge")).lower()
                    )
                )

                return {
                    "success": not has_errors,
                    "compiled": True,
                    "error_badge": compile_info.get("error_badge"),
                    "errors": compile_info.get("log_errors"),
                    "pdf_viewer_active": compile_info.get("has_pdf"),
                    "message": (
                        "Compilation finished successfully."
                        if not has_errors
                        else "Compilation completed with errors."
                    ),
                }
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    async def download_pdf(self, custom_filename: Optional[str] = None) -> Dict[str, Any]:
        """Download the compiled PDF from Overleaf and save it to OVERLEAF_OUTPUT_DIR."""
        async with self._lock:
            page = await self._ensure_browser()
            filename = custom_filename or f"resume_{int(time.time())}.pdf"
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            dest_path = self.output_dir / filename

            try:
                pdf_href = await page.evaluate(
                    """
                    () => {
                        const a = document.querySelector('a[href*="output.pdf"], a[aria-label*="Download PDF" i], a[download]');
                        return a ? a.getAttribute('href') : null;
                    }
                    """
                )

                if pdf_href:
                    full_url = (
                        f"https://www.overleaf.com{pdf_href}"
                        if pdf_href.startswith("/")
                        else pdf_href
                    )
                    response = await page.context.request.get(full_url)
                    if response.status == 200:
                        body = await response.body()
                        if len(body) > 1000 and body.startswith(b"%PDF"):
                            dest_path.write_bytes(body)
                            return {
                                "success": True,
                                "file_path": str(dest_path),
                                "file_name": filename,
                                "size_bytes": len(body),
                                "message": f"PDF successfully downloaded to {dest_path}",
                            }

                download_sel = "a[aria-label*='Download PDF' i], a[href*='output.pdf']"
                btn = page.locator(download_sel).first
                if await btn.is_visible(timeout=3000):
                    async with page.expect_download(timeout=15000) as download_info:
                        await btn.click()
                    download = await download_info.value
                    await download.save_as(str(dest_path))
                    return {
                        "success": True,
                        "file_path": str(dest_path),
                        "file_name": filename,
                        "size_bytes": dest_path.stat().st_size,
                        "message": f"PDF successfully downloaded to {dest_path}",
                    }

                return {
                    "success": False,
                    "error": "Could not download PDF. The project may need to be recompiled first.",
                }
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    async def take_screenshot(self, filename: Optional[str] = None) -> Dict[str, Any]:
        """Capture a screenshot of the current Overleaf page."""
        async with self._lock:
            page = await self._ensure_browser()
            try:
                name = filename or f"overleaf_screen_{int(time.time())}.png"
                if not name.endswith(".png"):
                    name += ".png"
                self.output_dir.mkdir(parents=True, exist_ok=True)
                path = self.output_dir / name
                await page.screenshot(path=str(path), full_page=False)
                return {"success": True, "screenshot_path": str(path)}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    async def sync_to_workspace(
        self,
        workspace_repo_path: Path,
        project_id_or_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download project ZIP or active CodeMirror buffer into workspace_repo_path."""
        status = await self.open_project(project_id_or_url)
        if not status.get("success"):
            raise RuntimeError(status.get("error") or "Failed to open Overleaf project in browser.")

        page = await self._ensure_browser()
        real_id = status.get("project_id")
        workspace_repo_path.mkdir(parents=True, exist_ok=True)
        extracted_files: List[str] = []

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

        if not extracted_files:
            latex_res = await self.get_latex_content()
            if latex_res.get("success") and latex_res.get("latex"):
                main_tex = workspace_repo_path / "main.tex"
                main_tex.write_text(latex_res["latex"], encoding="utf-8")
                extracted_files = ["main.tex"]

        if not (workspace_repo_path / ".git").exists():
            subprocess.run(["git", "init"], cwd=str(workspace_repo_path), capture_output=True)
            subprocess.run(["git", "add", "-A"], cwd=str(workspace_repo_path), capture_output=True)
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

    async def write_file_in_browser(
        self,
        file_path: str,
        new_content: str,
        project_id_or_url: Optional[str] = None,
        recompile: bool = True,
    ) -> Dict[str, Any]:
        """Open a file in Overleaf, update its CodeMirror editor content, and optionally recompile."""
        await self.open_project(project_id_or_url)
        filename = Path(file_path).name
        await self.open_file(filename)
        set_res = await self.set_latex_content(new_content)
        compile_res = await self.recompile() if recompile else None
        return {
            "pushed_via_browser": set_res.get("success", False),
            "file_path": file_path,
            "set_result": set_res,
            "compile_result": compile_res,
        }

    async def close(self) -> None:
        async with self._lock:
            if self._context:
                await self._context.close()
                self._context = None
                self._page = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None


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
