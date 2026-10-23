# LinkedIn Easy Apply & Job Search Browser Automation MCP Server

Connect **Claude**, **ChatGPT**, or **Gemini** directly to your own logged-in **Google Chrome** session (via Chrome Remote Debugging `--remote-debugging-port=9222` or a persistent Playwright profile) to search LinkedIn jobs, read job descriptions, auto-fill **LinkedIn Easy Apply** modals using your resume/profile data, and pause at the final **"Submit application"** button for human confirmation.

## Why Browser Automation (CDP) Instead of Unofficial LinkedIn APIs?

- **No Private API Reverse-Engineering or Cookie Scraping**: Uses your real, already-logged-in Chrome window over Chrome DevTools Protocol (`http://127.0.0.1:9222`).
- **Full "Easy Apply" Modal Support**: Reads multi-step modal inputs (`input`, `select`, `textarea`, radio buttons, file uploads) dynamically and matches them against your structured `profile.json`.
- **Strict Human-in-the-Loop Safety Gate**: `fill_easy_apply_step` and `autofill_easy_apply_until_review` advance through `Next` and `Review` buttons, and **always pause** when reaching `Submit application` until you explicitly confirm.

---

## 1. Installation

```bash
cd /home/vboxuser/Documents/mcp_server/overleaf_mcp_server/linkedin_mcp_server
pip install --user -e ".[dev]"
```

Create your candidate profile from the example template:

```bash
cp profile.example.json profile.json
```

Edit `profile.json` (or ask Claude/Gemini/ChatGPT to call `update_candidate_profile`) with your name, email, phone number, `resume_path`, `years_of_experience` per skill, and `work_authorization` preferences.

---

## 2. Start Chrome with Remote Debugging (`--remote-debugging-port=9222`)

You can either let the AI assistant call the `launch_chrome_debug_session` tool automatically, or launch Chrome yourself:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.linkedin_mcp_chrome_profile" "https://www.linkedin.com/jobs/"
```

Log into your LinkedIn account once in that Chrome window—your session stays saved in `~/.linkedin_mcp_chrome_profile`.

---

## 3. Connect to Claude, Gemini, or ChatGPT

### Claude Desktop / Gemini CLI / Antigravity (`mcpServers` config)

```json
{
  "mcpServers": {
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

### ChatGPT / HTTP Mode

```bash
linkedin-mcp --transport streamable-http --host 127.0.0.1 --port 8001
```

---

## 4. Available MCP Tools

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
