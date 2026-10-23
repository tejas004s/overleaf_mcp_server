# Overleaf & LinkedIn Browser Automation MCP Servers

[![MCP](https://img.shields.io/badge/Model_Context_Protocol-MCP-blue)](https://modelcontextprotocol.io)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Transports](https://img.shields.io/badge/Transports-stdio%20%7C%20SSE%20%7C%20Streamable--HTTP-purple)](#3-integrating-with-claude-gemini-and-chatgpt)

**Tags / Topics:** `mcp` `model-context-protocol` `overleaf` `latex` `bibtex` `linkedin` `easy-apply` `playwright` `chrome-cdp` `claude` `chatgpt` `gemini` `fastmcp`

A production-ready **Model Context Protocol (MCP)** suite designed for **Claude** (Desktop & Claude Code), **ChatGPT** (Custom MCP Connectors), and **Gemini** (CLI & Antigravity):

1. **`overleaf-mcp` (Root Package)** — Connects your AI assistant to **Overleaf** via the official **Overleaf Git Bridge** to read, edit, structure, audit citations/references, and push `.tex` & `.bib` files in real time.
2. **`linkedin-mcp` ([`./linkedin_mcp_server`](./linkedin_mcp_server))** — Connects via **Playwright / Chrome Remote Debugging (`--remote-debugging-port=9222`)** to your logged-in Chrome browser to search LinkedIn jobs, read job descriptions, auto-fill **LinkedIn Easy Apply** modals using your resume/profile data, and pause at the final **"Submit application"** button for human confirmation.

---

## Repository Structure

```text
overleaf_mcp_server/
├── src/overleaf_mcp/          # Overleaf Git Bridge MCP Server
│   ├── config.py              # Environment & multi-project registry
│   ├── git_client.py          # Git clone, pull --rebase, commit, push, secret redaction
│   ├── latex_parser.py        # Section parser, BibTeX manager, citation & syntax auditor
│   └── server.py              # MCP tools, prompts, stdio + HTTP/SSE Starlette server
├── tests/                     # End-to-end Overleaf MCP tests (simulated bare Git remote)
├── linkedin_mcp_server/       # LinkedIn Easy Apply Browser Automation MCP Server
│   ├── src/linkedin_mcp/
│   │   ├── browser_manager.py # Chrome CDP (:9222) & persistent context manager
│   │   ├── linkedin_automator.py # Job search, Easy Apply modal inspector & human-gated filler
│   │   ├── profile_store.py   # Candidate resume/profile JSON & question matcher
│   │   └── server.py          # LinkedIn MCP tools & multi-transport runner
│   ├── profile.example.json   # Template candidate profile for Easy Apply
│   └── tests/                 # LinkedIn MCP test suite
├── Dockerfile                 # Container image for remote HTTP/SSE deployment
├── docker-compose.yml         # Local & VPS Docker Compose setup
└── render.yaml                # One-click Render cloud deployment manifest
```

---

## 1. Overleaf Git Bridge MCP Server (`overleaf-mcp`)

### Prerequisites: Get Your Overleaf Git Token & Project ID

1. **Generate an Overleaf Git Token**:
   - Open [Overleaf Account Settings](https://www.overleaf.com/user/settings).
   - Scroll to **Git Integration** and click **Create Token**.
   - Copy the token (starts with `olp_...`).
2. **Find Your Overleaf Project ID**:
   - Open your project in Overleaf: `https://www.overleaf.com/project/<PROJECT_ID>`
   - Copy `<PROJECT_ID>` (or pass the full URL directly to `register_project`).

### Installation

```bash
pip install -e ".[dev]"
cp .env.example .env
```

### Overleaf MCP Tools

| Tool | Description |
| :--- | :--- |
| `register_project` | Register an Overleaf project alias by Project ID or Overleaf URL |
| `list_projects` | List all configured project aliases and default project |
| `sync_project` | Clone or `git pull --rebase` latest changes from Overleaf |
| `get_project_status` | Show Git status, uncommitted diffs, and recent Overleaf commit history |
| `list_files` | List all files in the project (with optional `.tex` / `.bib` filter) |
| `read_file` | Read the full contents of a file in the project |
| `write_file` | Create or overwrite a file and automatically commit & push to Overleaf |
| `edit_file_snippet` | Surgically replace an exact snippet inside a file and push to Overleaf |
| `delete_file` | Delete a file from the project and push to Overleaf |
| `push_changes` | Commit and push any pending local modifications to Overleaf |
| `get_document_outline` | Parse `\section`, `\subsection`, etc. hierarchy with line ranges |
| `read_section` | Read a specific LaTeX section by title or 0-based index |
| `update_section` | Replace a specific LaTeX section and push to Overleaf |
| `list_bibliography` | Parse and search BibTeX entries in `.bib` files |
| `add_or_update_bib_entry` | Add or update a BibTeX entry in `.bib` and push to Overleaf |
| `audit_references_and_citations` | Find missing citations, broken `\ref` links, unused `.bib` keys, and duplicate labels |
| `validate_and_compile` | Check LaTeX syntax (environments/braces) and run local `latexmk`/`pdflatex` if available |

---

## 2. LinkedIn Easy Apply Browser Automation MCP (`linkedin-mcp`)

See [`linkedin_mcp_server/README.md`](./linkedin_mcp_server/README.md) for full details.

### Installation & Setup

```bash
cd linkedin_mcp_server
pip install -e ".[dev]"
cp profile.example.json profile.json
```

Start Chrome with Remote Debugging enabled (or ask your AI assistant to run `launch_chrome_debug_session`):

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.linkedin_mcp_chrome_profile" "https://www.linkedin.com/jobs/"
```

### LinkedIn MCP Tools

| Tool | Description |
| :--- | :--- |
| `launch_chrome_debug_session` | Launch Chrome with `--remote-debugging-port=9222` and persistent profile |
| `check_linkedin_session` | Verify browser connection and check whether LinkedIn is logged in |
| `get_candidate_profile` | View the candidate's saved resume/profile JSON |
| `update_candidate_profile` | Update contact info, skill years of experience, visa status, or custom Q&A |
| `search_linkedin_jobs` | Search LinkedIn jobs with keywords, location, Easy Apply (`f_AL=true`), remote/hybrid, and recency filters |
| `get_linkedin_job_details` | Open a job listing and read the full job description and Easy Apply status |
| `start_easy_apply` | Click the **Easy Apply** button and inspect the first step's form fields |
| `inspect_easy_apply_modal` | Inspect current modal fields, profile-matched values, validation errors, and buttons |
| `fill_easy_apply_step` | Fill current modal step and click `Next`/`Review` (never clicks `Submit application`) |
| `autofill_easy_apply_until_review` | Walk through all Easy Apply steps automatically and pause at the final `Submit application` button |
| `submit_easy_apply` | Click the final `Submit application` button (requires explicit `confirm_submit=True`) |

---

## 3. Integrating with Claude, Gemini, and ChatGPT

### A. Claude Desktop (`claude_desktop_config.json`) & Gemini CLI (`~/.gemini/settings.json`)

```json
{
  "mcpServers": {
    "overleaf": {
      "command": "overleaf-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "OVERLEAF_GIT_TOKEN": "olp_your_git_token_here",
        "OVERLEAF_PROJECT_ID": "your_default_project_id"
      }
    },
    "linkedin-easy-apply": {
      "command": "linkedin-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "CHROME_CDP_URL": "http://127.0.0.1:9222",
        "LINKEDIN_PROFILE_PATH": "/absolute/path/to/profile.json"
      }
    }
  }
}
```

### B. Claude Code (CLI)

```bash
claude mcp add overleaf \
  -e OVERLEAF_GIT_TOKEN=olp_your_git_token_here \
  -e OVERLEAF_PROJECT_ID=your_default_project_id \
  -- overleaf-mcp --transport stdio

claude mcp add linkedin-easy-apply \
  -e CHROME_CDP_URL=http://127.0.0.1:9222 \
  -- linkedin-mcp --transport stdio
```

### C. ChatGPT (Developer Mode / Custom MCP Connector) & Docker Deployment

ChatGPT connects to remote MCP servers over HTTPS (`streamable-http` or `sse`).

```bash
# Run with Docker Compose on port 8000
OVERLEAF_GIT_TOKEN=olp_your_token \
OVERLEAF_PROJECT_ID=your_project_id \
MCP_TRANSPORT=streamable-http \
docker compose up --build -d
```

Or deploy directly to **Render**, **Railway**, **Fly.io**, or **Google Cloud Run** using the included [`Dockerfile`](./Dockerfile) and [`render.yaml`](./render.yaml).

---

## Running Tests

```bash
# Run Overleaf MCP tests
pytest -v

# Run LinkedIn MCP tests
pytest linkedin_mcp_server/tests -v
```
