"""Playwright Browser Manager supporting Chrome Remote Debugging (CDP) and Persistent Contexts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright


class BrowserSessionManager:
    """Manages a single connected Chrome CDP session or Playwright persistent context."""

    def __init__(
        self,
        cdp_url: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
        headless: Optional[bool] = None,
    ) -> None:
        self.cdp_url = (cdp_url or os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222")).strip()
        self.mode = os.getenv("LINKEDIN_BROWSER_MODE", "auto").strip().lower()
        default_profile_dir = Path(
            os.getenv("LINKEDIN_USER_DATA_DIR", "~/.linkedin_mcp_chrome_profile")
        ).expanduser()
        self.user_data_dir = user_data_dir or default_profile_dir
        self.headless = (
            headless
            if headless is not None
            else os.getenv("LINKEDIN_HEADLESS", "false").lower() in ("1", "true", "yes")
        )

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.connection_type: str = "disconnected"

    async def get_page(self) -> Page:
        """Return an active Playwright Page connected to Chrome CDP or persistent profile."""
        if self._page and not self._page.is_closed():
            return self._page

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        # 1. Try connecting to existing logged-in Chrome via CDP first (unless mode == 'persistent')
        if self.mode in ("auto", "cdp") and self.cdp_url:
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self.cdp_url, timeout=5000
                )
                contexts = self._browser.contexts
                if contexts:
                    self._context = contexts[0]
                else:
                    self._context = await self._browser.new_context()
                pages = self._context.pages
                self._page = pages[0] if pages else await self._context.new_page()
                self.connection_type = f"cdp ({self.cdp_url})"
                return self._page
            except Exception as cdp_err:
                if self.mode == "cdp":
                    raise RuntimeError(
                        f"Failed to connect to Chrome over CDP at {self.cdp_url}. "
                        "Start Chrome with: google-chrome --remote-debugging-port=9222 "
                        f"or use the launch_chrome_debug_session tool. Error: {cdp_err}"
                    ) from cdp_err

        # 2. Fallback to Playwright persistent context
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self.connection_type = f"persistent ({self.user_data_dir})"
        return self._page

    async def close(self) -> None:
        """Disconnect or close the browser context cleanly."""
        if self.connection_type.startswith("persistent") and self._context:
            await self._context.close()
        self._page = None
        self._context = None
        self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self.connection_type = "disconnected"

    def launch_system_chrome_cdp(self, port: int = 9222) -> Dict[str, Any]:
        """Spawn the user's system Chrome/Chromium browser with --remote-debugging-port enabled."""
        candidates = [
            os.getenv("CHROME_EXECUTABLE_PATH", ""),
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "brave-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        chrome_bin: Optional[str] = None
        for cand in candidates:
            if not cand:
                continue
            resolved = shutil.which(cand) or (cand if Path(cand).exists() else None)
            if resolved:
                chrome_bin = resolved
                break

        if not chrome_bin:
            raise FileNotFoundError(
                "Could not locate Google Chrome or Chromium executable. "
                "Set CHROME_EXECUTABLE_PATH or start Chrome manually with --remote-debugging-port=9222."
            )

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            chrome_bin,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self.user_data_dir}",
            "https://www.linkedin.com/jobs/",
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
            "user_data_dir": str(self.user_data_dir),
            "instructions": (
                "Chrome has been launched with remote debugging enabled. "
                "Log into your LinkedIn account in that window if not already logged in."
            ),
        }
