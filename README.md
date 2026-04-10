# Agent Marketplace — VS Code Setup Guide

## What You Have

```
agent-marketplace/
├── agent1_research.py     ← ResearchBot  (port 8001)
├── agent2_writer.py       ← WriteBot     (port 8002)
├── agent3_analyst.py      ← AnalystBot   (port 8003)
├── orchestrator.py        ← A2A Orchestrator (port 8000)
├── marketplace.html       ← UI (open directly in browser)
├── requirements.txt
└── README.md
```

---

## Step 1 — Open in VS Code

1. Open VS Code
2. Go to **File → Open Folder** → select the `agent-marketplace` folder
3. Open the built-in terminal: **Terminal → New Terminal** (or Ctrl+`)

---

## Step 2 — Install Python Dependencies

In the VS Code terminal, run:

```bash
pip install -r requirements.txt
```

> If you have multiple Python versions, use `pip3` instead of `pip`.

---

## Step 3 — Set Your OpenRouter API Key

You need an OpenRouter API key to use Grok. Get one free at https://openrouter.ai/keys

**Windows (PowerShell):**
```powershell
$env:OPENROUTER_API_KEY = "sk-or-v1-your-key-here"
```

**Mac / Linux:**
```bash
export OPENROUTER_API_KEY="sk-or-v1-your-key-here"
```

> Tip: You can also enter the key directly in the marketplace UI — no terminal needed.

---

## Step 4 — Run Each Agent (4 terminals)

You need 4 separate terminals running at the same time.

### How to open multiple terminals in VS Code:
- Click the **+** button in the terminal panel (top right of terminal)
- Or press `Ctrl+Shift+5` to split the terminal

---

### Terminal 1 — ResearchBot (port 8001)
```bash
python agent1_research.py
```
You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
```

---

### Terminal 2 — WriteBot (port 8002)
```bash
python agent2_writer.py
```
You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8002 (Press CTRL+C to quit)
```

---

### Terminal 3 — AnalystBot (port 8003)
```bash
python agent3_analyst.py
```
You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8003 (Press CTRL+C to quit)
```

---

### Terminal 4 — Orchestrator (port 8000)
```bash
python orchestrator.py
```
You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

## Step 5 — Open the Marketplace UI

Simply open `marketplace.html` in your browser:
- In VS Code: right-click `marketplace.html` → **Open with Live Server** (if you have the Live Server extension)
- OR: find the file in your file explorer and double-click it to open in your browser

---

## Step 6 — Use the Marketplace

1. **Enter your OpenRouter API key** in the yellow bar at the top → click Save
2. **Click any agent** in the left sidebar (ResearchBot, WriteBot, AnalystBot)
3. **Click "▶ Use Agent"** tab, fill in the form, and click Run
4. **For multi-agent pipelines**, click any pipeline in the sidebar (e.g. "Research → Write")
5. Results appear below with a tab for each agent's output

---

## Agent Tokens (for direct API calls)

| Agent | Port | Token |
|-------|------|-------|
| ResearchBot | 8001 | `research-token-abc123` |
| WriteBot | 8002 | `writer-token-def456` |
| AnalystBot | 8003 | `analyst-token-ghi789` |

---

## Test Agents Are Running (optional)

Open a 5th terminal and test:

```bash
# Check ResearchBot is alive
curl http://localhost:8001/health

# Check AgentCard (A2A discovery)
curl http://localhost:8001/.well-known/agent.json

# Check Orchestrator
curl http://localhost:8000/pipelines
```

---

## Demo Mode (no backend needed)

If the backend agents aren't running, the UI still works in **DEMO MODE** — it shows simulated responses so you can see the interface. Results will be labeled "DEMO MODE" in orange.

---

## Troubleshooting

**"ModuleNotFoundError"** → Run `pip install -r requirements.txt` again

**"Address already in use"** → Another process is using that port. Kill it:
- Mac/Linux: `lsof -ti:8001 | xargs kill`
- Windows: `netstat -ano | findstr :8001` then `taskkill /PID <pid> /F`

**API key not working** → Make sure you set `OPENROUTER_API_KEY` in the terminal BEFORE running the agent scripts, OR enter it in the UI's yellow bar

**CORS error in browser** → The agents already have CORS enabled. If you still get errors, try opening the HTML file from VS Code's Live Server instead of double-clicking

---

## Architecture: How A2A Protocol Works

```
marketplace.html
      │
      │ (direct fetch if single agent)
      │ (POST /orchestrate if pipeline)
      ▼
orchestrator.py  :8000
  1. GET /.well-known/agent.json   ← discovers AgentCard
  2. POST /a2a/execute             ← runs agent with X-Agent-Token
  3. takes a2a_passthrough from response
  4. passes it as `context` to next agent
      │
   ┌──┴──────────────────────┐
   ▼                         ▼
agent1 :8001          agent2 :8002          agent3 :8003
ResearchBot           WriteBot              AnalystBot
```

Each agent passes its output via `a2a_passthrough` so the next agent
in the pipeline has full context from all previous steps.
