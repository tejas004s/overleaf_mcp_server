# Overleaf & LinkedIn Browser Automation MCP Servers

[![MCP](https://img.shields.io/badge/Model_Context_Protocol-MCP-blue)](https://modelcontextprotocol.io)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Transports](https://img.shields.io/badge/Transports-stdio%20%7C%20SSE%20%7C%20Streamable--HTTP-purple)](#step-4--connect-to-claude-chatgpt-or-gemini)

**Tags / Topics:** `mcp` `model-context-protocol` `overleaf` `latex` `bibtex` `linkedin` `easy-apply` `playwright` `chrome-cdp` `claude` `chatgpt` `gemini` `fastmcp`

Connect **Claude**, **ChatGPT**, or **Gemini** to your **Overleaf** account (works on **Free Tier** via Playwright Browser Automation as well as Paid Tier via Git Bridge) AND to **LinkedIn Easy Apply** via Chrome Remote Debugging.

Give Claude a job description and your Overleaf project URL—it will open your resume/paper on Overleaf, tailor the LaTeX, recompile, check for errors, and return a **clickable PDF download link**.

---

## Cloud Deployment (Railway / Render — Recommended)

### Step 1 — Deploy to Railway or Render

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select `tejas004s/overleaf_mcp_server` (uses [`railway.json`](./railway.json) and [`Dockerfile`](./Dockerfile) automatically).
2. Under **Settings → Networking**, click **Generate Domain** and copy your public URL (e.g. `https://your-app.up.railway.app`).

### Step 2 — Export Your Overleaf Session Locally

Because Overleaf's Free Tier does not provide API/Git keys, you log in once locally in a visible browser and export your session state as a single base64 environment variable (`OVERLEAF_STORAGE_STATE_B64`):

```bash
git clone https://github.com/tejas004s/overleaf_mcp_server.git
cd overleaf_mcp_server
pip install -r requirements.txt
playwright install chromium

python3 setup_auth.py       # Opens a browser window — log in to Overleaf, then press Enter
python3 export_session.py   # Prints your authenticated session as OVERLEAF_STORAGE_STATE_B64
```

### Step 3 — Set Cloud Environment Variables

In **Railway → Variables** (or Render Environment Variables), add:

| Variable | Value |
| :--- | :--- |
| `OVERLEAF_STORAGE_STATE_B64` | *(Paste the base64 string printed by `export_session.py`)* |
| `MCP_TRANSPORT` | `streamable-http` |

*(Alternative: You can also set `OVERLEAF_SESSION_COOKIE` to your raw `overleaf_session2=...` cookie from Chrome DevTools).*

### Step 4 — Connect to Claude, ChatGPT, or Gemini

- **Interactive Web Test Console**: Open `https://your-app.up.railway.app/` in your browser to test login status and live LaTeX project reading with one click.
- **Claude.ai (Web) / ChatGPT Connectors**:
  Go to **Settings → Integrations → Add Integration** and paste:
  ```text
  https://your-app.up.railway.app/mcp
  ```
- **Claude Desktop (`claude_desktop_config.json`) / Gemini CLI (`~/.gemini/settings.json`)**:
  ```json
  {
    "mcpServers": {
      "overleaf": {
        "url": "https://your-app.up.railway.app/mcp"
      }
    }
  }
  ```

---

## Local Setup (HTTP or `stdio`)

```bash
python3 setup_auth.py   # Log in to Overleaf once (saves to ./browser_data)
./run_server.sh         # Starts Streamable-HTTP server + Test Console at http://127.0.0.1:8000/mcp
```

Or run directly via `stdio` in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "overleaf": {
      "command": "/home/vboxuser/.local/bin/overleaf-mcp",
      "args": ["--transport", "stdio", "--no-headless"],
      "env": {
        "OVERLEAF_SHARE_URL": "https://www.overleaf.com/project/<YOUR_PROJECT_ID>"
      }
    },
    "linkedin-easy-apply": {
      "command": "/home/vboxuser/.local/bin/linkedin-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "CHROME_CDP_URL": "http://127.0.0.1:9222",
        "LINKEDIN_PROFILE_PATH": "/home/vboxuser/Documents/mcp_server/overleaf_mcp_server/linkedin_mcp_server/profile.json"
      }
    }
  }
}
```

---

## Available Overleaf MCP Tools

| Tool | Description |
| :--- | :--- |
| `overleaf_status` | Check Overleaf browser authentication status |
| `overleaf_open_project` | Open an Overleaf project by URL, share link, or ID |
| `overleaf_list_files` | List files in the Overleaf project file tree |
| `overleaf_open_file` | Switch the active editor to a specific file (`main.tex`, `references.bib`, etc.) |
| `overleaf_get_latex` | Read complete LaTeX source from Overleaf's CodeMirror 6 editor |
| `overleaf_set_latex` | Write updated LaTeX code directly to Overleaf's editor |
| `overleaf_recompile` | Trigger Recompile on Overleaf and inspect compile errors/warnings |
| `overleaf_download_pdf` | Download the compiled PDF and return a clickable `/download/<file>.pdf` URL |
| `overleaf_take_screenshot` | Capture a screenshot of the Overleaf editor and PDF viewer |
| `tailor_resume_instructions` | Best-practice instructions for tailoring a LaTeX resume to a Job Description |
| `get_document_outline` | Parse `\section`, `\subsection`, etc. hierarchy with line numbers |
| `read_section` / `update_section` | Read or replace a specific section by title or index |
| `list_bibliography` / `add_or_update_bib_entry` | Search and manage `.bib` entries |
| `audit_references_and_citations` | Detect missing citations, broken `\ref` links, and duplicate `\label`s |

---

## LinkedIn Easy Apply Browser Automation MCP (`linkedin-mcp`)

Located in [`./linkedin_mcp_server`](./linkedin_mcp_server/README.md). Connects to your logged-in Chrome browser (`--remote-debugging-port=9222`) to search LinkedIn jobs, read job descriptions, auto-fill **Easy Apply** modals using your `profile.json`, and pause at the final **Submit application** button for human confirmation.
