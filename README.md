# Overleaf MCP Server for Claude, ChatGPT & Gemini

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/tejas004s/overleaf_mcp_server)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-MCP-blue)](https://modelcontextprotocol.io)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

Connect **Claude** (`claude.ai` Web & Claude Desktop), **ChatGPT**, or **Gemini** directly to your **Overleaf** account—**even on the Overleaf Free Tier** (no paid Overleaf API/Git subscription or terminal setup required).

Give Claude your details or a Job Description (JD), and it will:
1. Open your Overleaf project (or create a brand-new blank project)
2. Write or tailor a 1-page ATS-friendly LaTeX resume
3. Trigger **Recompile** on Overleaf and verify zero LaTeX errors
4. Return a **clickable PDF download link** right inside your chat

---

## Quick Start: Deploy on Render in 3 Minutes (No Terminal Needed)

### Step 1 — Fork & Deploy to Render

1. **Fork** this repository to your GitHub account.
2. Go to [dashboard.render.com](https://dashboard.render.com) → click **New +** → select **Web Service** (or click the **Deploy to Render** button above).
3. Select your forked repository (`overleaf_mcp_server`).
4. Ensure the following defaults are selected:
   - **Runtime**: `Docker` (auto-detected from [`Dockerfile`](./Dockerfile))
   - **Branch**: `main`
5. Click **Deploy Web Service** and wait ~2–3 minutes for the container build to finish.
6. Copy your public Render URL (e.g., `https://overleaf-mcp-server-xxxx.onrender.com`).

---

### Step 2 — Connect Your Overleaf Project in the Web Console

1. In **Overleaf**, open your resume/paper project → click **Share** (top right) → **Turn on link sharing** → copy the **Link to edit** (`https://www.overleaf.com/project/<ID>/share#...`).
2. Open your Render URL (`https://overleaf-mcp-server-xxxx.onrender.com`) in your browser to access the **Overleaf MCP Easy Setup Console**:
   - Paste your **Overleaf Share Link URL** into Box 2.
   - *(Optional)* If your Overleaf project requires account login, open Overleaf in Chrome → press `F12` (DevTools) → **Application** tab → **Cookies** → `https://www.overleaf.com` → copy the value of `overleaf_session2`, and paste it into the **Overleaf Session Cookie** field.
   - Click **Save & Test Connection**, then click **Open Project & Read LaTeX** to confirm it reads your project live.
   - Click **Copy URL** to copy your MCP endpoint:
     ```text
     https://overleaf-mcp-server-xxxx.onrender.com/mcp
     ```

*(Tip: You can also skip the web console and configure your session directly inside Claude chat using the `overleaf_configure_session` tool!)*

---

### Step 3 — Connect to Claude

#### Option A: Claude.ai (Web / Mobile)
1. Go to [claude.ai](https://claude.ai) → **Settings** → **Integrations** (or **Connectors**) → **Add Custom Integration**.
2. Enter:
   - **Name**: `Overleaf`
   - **URL**: `https://overleaf-mcp-server-xxxx.onrender.com/mcp`
3. Click **Connect**. *(The server includes built-in OAuth 2.1 Dynamic Client Registration (`/register`, `/authorize`, `/token`), so Claude's sign-in handshake completes automatically!)*

#### Option B: Claude Desktop (`claude_desktop_config.json`)
Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "overleaf": {
      "url": "https://overleaf-mcp-server-xxxx.onrender.com/mcp"
    }
  }
}
```

---

## Step 4 — Example Prompts to Try in Claude

### 1. Create a Brand-New Resume from Scratch
```text
Please create a 1-page ATS-friendly LaTeX resume for me on Overleaf:
1. Open my Overleaf project: https://www.overleaf.com/project/<YOUR_SHARE_LINK>
2. Call `get_resume_latex_template` and `tailor_resume_instructions`.
3. Fill in my details:
   - Name: [Your Name]
   - Contact: [Email | Phone | LinkedIn | GitHub]
   - Education: [University, Degree, GPA, Graduation Date]
   - Skills: [Languages, Frameworks, Cloud/DevOps]
   - Experience & Projects: [Paste your rough notes or old resume text]
4. Write the complete LaTeX to Overleaf using `overleaf_set_latex`.
5. Run `overleaf_recompile` to verify 0 errors, then call `overleaf_download_pdf` and give me the clickable PDF download link.
```

### 2. Tailor Your Existing Overleaf Resume to a Job Description
```text
Here is the Job Description I am applying for:
"""
[Paste Job Description]
"""

My Overleaf resume link is: https://www.overleaf.com/project/<YOUR_SHARE_LINK>

Please open my project, read the current LaTeX with `overleaf_get_latex`, tailor my summary, skills, and experience bullets to match this JD (keeping it strictly 1 page), update Overleaf with `overleaf_set_latex`, recompile with `overleaf_recompile`, and give me the clickable PDF download link using `overleaf_download_pdf`.
```

---

## Available Overleaf MCP Tools

| Tool | Description |
| :--- | :--- |
| `overleaf_configure_session` | Set your Overleaf Share Link or `overleaf_session2` cookie directly from chat |
| `overleaf_status` | Check Overleaf browser authentication status |
| `overleaf_open_project` | Open an Overleaf project by URL, share link, or Project ID |
| `overleaf_create_blank_project` | Create a brand-new Blank Project on Overleaf |
| `get_resume_latex_template` | Retrieve a self-contained 1-page ATS-friendly LaTeX resume template |
| `tailor_resume_instructions` | Best-practice guidelines (XYZ formula, LaTeX escaping, ATS keywords) |
| `overleaf_list_files` | List all files in the Overleaf project file tree |
| `overleaf_open_file` | Switch the active Overleaf editor to a specific file (`main.tex`, `references.bib`, etc.) |
| `overleaf_get_latex` | Read complete LaTeX source from Overleaf's CodeMirror 6 editor |
| `overleaf_set_latex` | Write updated LaTeX code directly into Overleaf's editor |
| `overleaf_recompile` | Trigger Recompile on Overleaf and inspect any compile errors/warnings |
| `overleaf_download_pdf` | Download the compiled PDF and return a clickable `/download/<file>.pdf` URL |
| `overleaf_take_screenshot` | Capture a screenshot of the Overleaf editor and PDF preview |
| `get_document_outline` | Parse `\section`, `\subsection`, etc. hierarchy with line numbers |
| `read_section` / `update_section` | Read or replace a specific LaTeX section by title or index |
| `list_bibliography` / `add_or_update_bib_entry` | Search and manage BibTeX `.bib` entries |
| `audit_references_and_citations` | Detect missing citations, broken `\ref` links, and duplicate `\label`s |

---

## Alternative: Deploy on Railway or Run Locally

### Deploy on Railway
1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select your fork (uses [`railway.json`](./railway.json) automatically).
2. Under **Settings → Networking**, click **Generate Domain** and open `https://your-app.up.railway.app` to configure your Overleaf link in the Web Console.

### Run Locally (`http://127.0.0.1:8000/mcp`)
```bash
git clone https://github.com/tejas004s/overleaf_mcp_server.git
cd overleaf_mcp_server
pip install -r requirements.txt
playwright install chromium

python3 setup_auth.py   # Optional: log in once in a visible browser window
./run_server.sh         # Starts server + Web Console at http://127.0.0.1:8000
```

---

## Bonus: LinkedIn Easy Apply Browser Automation MCP (`./linkedin_mcp_server`)

This repository also includes a **LinkedIn Easy Apply Browser Automation MCP Server** in [`./linkedin_mcp_server`](./linkedin_mcp_server/README.md) that connects to your logged-in Chrome browser (`--remote-debugging-port=9222`) to search LinkedIn jobs, read job descriptions, auto-fill **Easy Apply** modals using your resume/profile data, and pause at the final **Submit application** button for human confirmation.

---

## License

[MIT](https://opensource.org/licenses/MIT)
