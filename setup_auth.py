#!/usr/bin/env python3
"""
Overleaf One-Time Authentication Setup

Launches a visible Chrome/Chromium browser with your persistent session profile (./browser_data).
Log in to Overleaf (via Email, Google, SSO, or open your Share URL).
Once you are logged into your dashboard or project, press Enter in the terminal.
Your session and cookies will be saved for all subsequent MCP calls and can be exported
with `python3 export_session.py` for Railway / Render cloud deployment!
"""

import asyncio
import os
import sys
from playwright.async_api import async_playwright

from overleaf_mcp.browser_client import OVERLEAF_PROFILE_DIR, OverleafBrowserClient


async def setup_auth() -> None:
    share_url = os.getenv("OVERLEAF_SHARE_URL", "").strip()
    start_url = share_url or "https://www.overleaf.com/login"

    print("=" * 65)
    print("OVERLEAF MCP - ONE-TIME LOGIN SETUP")
    print("=" * 65)
    print(f"Profile directory : {OVERLEAF_PROFILE_DIR}")
    print(f"Opening URL       : {start_url}")
    print("Please log in to your Overleaf account in the browser window.")
    print("=" * 65)

    chrome_bin = OverleafBrowserClient.find_system_chrome()

    async with async_playwright() as p:
        launch_kwargs = {
            "user_data_dir": str(OVERLEAF_PROFILE_DIR),
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            "viewport": {"width": 1280, "height": 800},
        }
        try:
            if not os.path.exists(p.chromium.executable_path) and chrome_bin:
                launch_kwargs["executable_path"] = chrome_bin
        except Exception:
            if chrome_bin:
                launch_kwargs["executable_path"] = chrome_bin

        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(start_url, wait_until="domcontentloaded")

        print("\nBrowser is open! Log in now.")

        async def monitor_url() -> None:
            while True:
                try:
                    if "/project" in page.url and "/login" not in page.url:
                        print(f"\n[Detected Login / Project] Current URL: {page.url}")
                        print("Authentication detected! Press [ENTER] in this terminal to save.")
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)

        monitor_task = asyncio.create_task(monitor_url())
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            input,
            "Press [ENTER] in this terminal once you have logged in to complete setup: ",
        )

        monitor_task.cancel()
        print("\nSaving session and closing browser...")
        await context.close()
        print("✅ Success! Your Overleaf session has been saved to ./browser_data")
        print("Next step for Cloud Deployment (Railway / Render):")
        print("  Run: python3 export_session.py")


if __name__ == "__main__":
    try:
        asyncio.run(setup_auth())
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        sys.exit(0)
