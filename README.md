# Overleaf MCP Server (Zero-CLI Deploy for Claude, ChatGPT & Gemini)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/tejas004s/overleaf_mcp_server)

Connect **Claude** to your **Overleaf** project in **2 minutes**—with **zero terminal commands** required.

---

## 3-Step Setup (Render + Claude)

### Step 1: Click Deploy on Render
1. Click the **[Deploy to Render](https://render.com/deploy?repo=https://github.com/tejas004s/overleaf_mcp_server)** button above (or go to [dashboard.render.com](https://dashboard.render.com) → **New +** → **Web Service** → select **`tejas004s/overleaf_mcp_server`**).
2. Click **Deploy** (no environment variables are required to deploy—your Overleaf share link is already pre-configured in [`render.yaml`](./render.yaml)!).

### Step 2: Open Your Render URL in the Browser
Once Render finishes deploying, open your app URL (`https://overleaf-mcp-server-xxxx.onrender.com`):
- You will see the **Overleaf MCP Easy Setup Console**.
- Your Overleaf share link (`https://www.overleaf.com/project/6ab69fcdfed103759283b936/share#...`) is already filled in.
- *(If Overleaf asks for login, paste your `overleaf_session2` cookie right into the webpage and click **Save & Test Connection**).*
- Click **Copy URL** to copy `https://overleaf-mcp-server-xxxx.onrender.com/mcp`.

### Step 3: Add to Claude
- **Claude Web (`claude.ai`)**: Go to **Settings → Integrations → Add Integration** and paste `https://overleaf-mcp-server-xxxx.onrender.com/mcp`.
- **Claude Desktop**: Add to `claude_desktop_config.json`:
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

## Ask Claude to Create Your Resume

Paste this into Claude:

> *"Open my Overleaf project, generate a 1-page LaTeX resume using `get_resume_latex_template` with my details, write it to Overleaf with `overleaf_set_latex`, recompile with `overleaf_recompile`, and give me the PDF download link with `overleaf_download_pdf`."*
