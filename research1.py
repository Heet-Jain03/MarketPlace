"""
Agent 1: Research Agent
AgentCard-based A2A compliant agent — secured with JWT user auth + internal token
"""
from fastapi.responses import HTMLResponse
import json
import os
import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

from llm_client import (
    format_llm_http_error, post_chat, resolve_env_api_key,
    verify_user_jwt, verify_internal_agent_token
)

# ── Agent Token (internal service-to-service only, loaded from env) ───────────
# NEVER hardcode this — set AGENT_TOKEN_RESEARCH in your environment / docker-compose
AGENT_TOKEN = os.environ.get("AGENT_TOKEN_RESEARCH", "research-token-abc123")

# ── AgentCard ─────────────────────────────────────────────────────────────────
AGENT_CARD = {
    "schema_version": "1.0",
    "agent_id":       "research-agent-001",
    "name":           "ResearchBot",
    "version":        "1.0.0",
    "description":    "A powerful research agent that searches, synthesizes, and summarizes information on any topic. Produces structured reports with key insights.",
    "author":         "AgentMarketplace",
    "icon":           "🔬",
    "price_usd":      9.99,
    "category":       "Research & Analysis",
    "capabilities":   ["Deep topic research","Multi-source synthesis","Structured report generation","Citation formatting","Trend analysis"],
    "input_schema": {
        "type": "object",
        "properties": {
            "query":  {"type": "string",  "description": "Research topic or question"},
            "depth":  {"type": "string",  "enum": ["brief","standard","deep"],    "default": "standard"},
            "format": {"type": "string",  "enum": ["bullets","report","summary"], "default": "report"}
        },
        "required": ["query"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "title":        {"type": "string"},
            "summary":      {"type": "string"},
            "key_findings": {"type": "array", "items": {"type": "string"}},
            "raw_text":     {"type": "string"}
        }
    },
    "a2a_endpoints": {
        "execute": "/a2a/execute",
        "status":  "/a2a/status",
        "card":    "/.well-known/agent.json"
    },
    "auth": {
        "type":   "bearer",
        "header": "Authorization",
        "note":   "Requires valid user JWT from Auth Service"
    },
    "orchestration_hints": {
        "can_feed_into":  ["writer-agent-002","analyst-agent-003"],
        "output_key":     "research_context",
        "typical_pipeline": "research → writer or research → analyst"
    }
}

app = FastAPI(title="ResearchBot Agent", version="1.0.0", docs_url=None, redoc_url=None)
@app.get("/", response_class=HTMLResponse)
async def ui_page():
    return """
    <html>
    <head>
        <title>ResearchBot</title>
        <style>
            body { font-family: Arial; padding: 40px; background: #f5f5f5; }
            .box { max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 10px; }
            textarea, select, button { margin-top: 10px; width: 100%; padding: 10px; }
            .result { margin-top: 20px; padding: 15px; border: 1px solid #ccc; border-radius: 8px; }
        </style>
    </head>
    <body>

    <div class="box">
        <h2>🔬 ResearchBot</h2>

        <label>Query:</label>
        <textarea id="query">what is AI</textarea>

        <label>Depth:</label>
        <select id="depth">
            <option value="brief">Brief</option>
            <option value="standard" selected>Standard</option>
            <option value="deep">Deep</option>
        </select>

        <label>Format:</label>
        <select id="format">
            <option value="report">Report</option>
            <option value="summary">Summary</option>
            <option value="bullets">Bullets</option>
        </select>

        <button onclick="run()">Run ResearchBot</button>

        <div class="result" id="output"></div>
    </div>

    <script>
    async function run() {
        const query = document.getElementById("query").value;
        const depth = document.getElementById("depth").value;
        const format = document.getElementById("format").value;

        const res = await fetch(`/a2a/execute?query=${encodeURIComponent(query)}&depth=${depth}&format=${format}`);
        const data = await res.json();

        document.getElementById("output").innerHTML = `
            <h3>${data.result.title}</h3>
            <p><b>Summary:</b> ${data.result.summary}</p>
            <ul>${data.result.key_findings.map(i => `<li>${i}</li>`).join("")}</ul>
        `;
    }
    </script>

    </body>
    </html>
    """
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ExecuteRequest(BaseModel):
    query:   str
    depth:   str            = "standard"
    format:  str            = "report"
    context: Optional[dict] = None

# 🔥 COMMON LOGIC FUNCTION (ADD THIS)
async def run_agent_logic(req: ExecuteRequest, api_key: str):
    depth_map = {
        "brief": "2-3 paragraphs",
        "standard": "5-6 paragraphs",
        "deep": "comprehensive multi-section report"
    }

    prior_context = ""
    if req.context:
        prior_context = f"\n\nAdditional context:\n{json.dumps(req.context, indent=2)}"

    system_prompt = (
        f"You are ResearchBot, an expert research agent. "
        f"Produce a {depth_map.get(req.depth, '5-6 paragraphs')} research response in {req.format} format. "
        f"Return JSON with keys: title, summary, key_findings, raw_text."
    )

    user_prompt = f"Research this topic thoroughly: {req.query}{prior_context}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    async with httpx.AsyncClient() as client:
        resp = await post_chat(client, api_key, messages, timeout=60)

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=format_llm_http_error(resp))

    content = resp.json()["choices"][0]["message"]["content"]

    try:
        result = json.loads(content)
    except:
        result = {
            "title": req.query,
            "summary": content,
            "key_findings": [],
            "raw_text": content
        }

    return {
        "agent_id": AGENT_CARD["agent_id"],
        "status": "success",
        "result": result
    }

@app.get("/.well-known/agent.json")
async def get_agent_card():
    """Public A2A AgentCard discovery — token fields are intentionally omitted"""
    safe_card = {k: v for k, v in AGENT_CARD.items()}
    return safe_card

@app.get("/health")
async def health():
    return {"status": "ok", "agent": AGENT_CARD["agent_id"]}

@app.post("/a2a/execute")
async def execute(
    req: ExecuteRequest,
    authorization: Optional[str] = Header(None),
    x_agent_token: Optional[str] = Header(None),
    x_openrouter_api_key: Optional[str] = Header(None, alias="X-OpenRouter-API-Key"),
):
    # ✅ MUST BE INDENTED (4 spaces)

    # Auth: orchestrator OR user
    if x_agent_token:
        verify_internal_agent_token(AGENT_TOKEN, x_agent_token)

    elif authorization:
        user = verify_user_jwt(authorization)

        # ✅ PURCHASE CHECK
        agent_id = "research-agent-001"

        if agent_id not in user.get("purchased_agents", []):
            raise HTTPException(status_code=403, detail="Buy agent first")

    else:
        raise HTTPException(status_code=401, detail="Authentication required")

    # ── CONTINUE NORMAL FLOW
    api_key = (x_openrouter_api_key or "").strip() or resolve_env_api_key()

    if not api_key:
        raise HTTPException(status_code=401, detail="Missing LLM API key")

    # ── INPUT GUARDRAILS ──────────────────────────────────────────────────────
    query = req.query.strip()

    # 1. Empty input
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty. Please enter a research topic.")

    # 2. Too short — meaningless input
    if len(query) < 3:
        raise HTTPException(status_code=400, detail="Query is too short. Please enter at least 3 characters.")

    # 3. Too long — prevent prompt stuffing / abuse
    if len(query) > 2000:
        raise HTTPException(status_code=400, detail="Query is too long (max 2000 characters).")

    # 4. Input looks like an API key — user pasted key in wrong field
    if (query.startswith("gsk_") or query.startswith("sk-or-v1-") or
            query.startswith("sk-") or query.startswith("Bearer ")):
        raise HTTPException(status_code=400, detail="Invalid input: please enter a research topic, not an API key.")

    # 5. Input is only whitespace or punctuation — no real content
    import re as _re
    if not _re.search(r"[a-zA-Z0-9]", query):
        raise HTTPException(status_code=400, detail="Query must contain letters or numbers.")

    # 6. Prompt injection / jailbreak patterns
    _BLOCKED = [
        "ignore previous instructions", "ignore all instructions",
        "disregard the above", "forget everything", "jailbreak",
        "you are now", "act as ", "pretend you are",
        "override instructions", "\n\nsystem:", "\\n\\nsystem:"
    ]
    ql = query.lower()
    for pat in _BLOCKED:
        if pat in ql:
            raise HTTPException(status_code=400, detail="Input contains disallowed content.")
    # ─────────────────────────────────────────────────────────────────────────

    return await run_agent_logic(req, api_key)


# 🔥 Browser-friendly GET endpoint (for demo/testing only)
from fastapi.responses import HTMLResponse

@app.get("/a2a/execute")
async def execute_get(
    query: str = None,
    depth: str = "standard",
    format: str = "report"
):
    # 👉 If NO query → show UI
    if not query:
        return HTMLResponse("""
        <html>
        <head>
            <title>ResearchBot</title>
            <style>
                body { font-family: Arial; padding: 40px; background: #f5f5f5; }
                .box { max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 10px; }
                textarea, select, button { margin-top: 10px; width: 100%; padding: 10px; }
                .result { margin-top: 20px; padding: 15px; border: 1px solid #ccc; border-radius: 8px; }
            </style>
        </head>
        <body>

        <div class="box">
            <h2>🔬 ResearchBot</h2>

            <textarea id="query">what is AI</textarea>

            <select id="depth">
                <option value="brief">Brief</option>
                <option value="standard" selected>Standard</option>
                <option value="deep">Deep</option>
            </select>

            <select id="format">
                <option value="report">Report</option>
                <option value="summary">Summary</option>
                <option value="bullets">Bullets</option>
            </select>

            <button onclick="run()">Run</button>

            <div class="result" id="output"></div>
        </div>

        <script>
        window.run = async function() {
            console.log("RUN CLICKED");
                            
            const query = document.getElementById("query").value;
            const depth = document.getElementById("depth").value;
            const format = document.getElementById("format").value;

            const res = await fetch(`?query=${encodeURIComponent(query)}&depth=${depth}&format=${format}`);
            const data = await res.json();

            document.getElementById("output").innerHTML = `
                <h3>${data.result.title}</h3>
                <p>${data.result.summary}</p>
                <ul>${
                    (data.result.key_findings || [])
                        .map(i => `<li>${i}</li>`)
                        .join("")
                }</ul>
            `;
        }
        </script>

        </body>
        </html>
        """)

    # 👉 If query exists → run agent
    try:
        req = ExecuteRequest(query=query, depth=depth, format=format)

        api_key = resolve_env_api_key()
        if not api_key:
            raise HTTPException(status_code=401, detail="Missing API key")

        depth_map = {
            "brief": "2-3 paragraphs",
            "standard": "5-6 paragraphs",
            "deep": "detailed report"
        }

        system_prompt = f"Research in {depth_map.get(depth)} and return JSON"
        user_prompt = f"Research this: {query}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        async with httpx.AsyncClient() as client:
            resp = await post_chat(client, api_key, messages, timeout=60)

        content = resp.json()["choices"][0]["message"]["content"]

        try:
            result = json.loads(content)
        except:
            result = {
                "title": query,
                "summary": content,
                "key_findings": [],
                "raw_text": content
            }

        return {
            "agent_id": AGENT_CARD["agent_id"],
            "status": "success",
            "result": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/a2a/status")
async def status():
    return {"agent_id": AGENT_CARD["agent_id"], "status": "ready", "load": "low"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)