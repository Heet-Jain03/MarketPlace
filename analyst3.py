"""
Agent 3: Data Analyst Agent
AgentCard-based A2A compliant agent — secured with JWT user auth + internal token
"""
from fastapi.responses import HTMLResponse
import json
import os
import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

from llm_client import (
    format_llm_http_error, post_chat, resolve_env_api_key,
    verify_user_jwt, verify_internal_agent_token
)

AGENT_TOKEN = os.environ.get("AGENT_TOKEN_ANALYST", "analyst-token-ghi789")

AGENT_CARD = {
    "schema_version": "1.0",
    "agent_id":       "analyst-agent-003",
    "name":           "AnalystBot",
    "version":        "1.0.0",
    "description":    "A sharp data analyst agent that extracts insights, identifies patterns, performs SWOT analysis, generates actionable recommendations, and creates visualization blueprints.",
    "author":         "AgentMarketplace",
    "icon":           "📊",
    "price_usd":      12.99,
    "category":       "Data & Analytics",
    "capabilities":   ["Data pattern recognition","SWOT analysis","Trend forecasting","Competitive analysis","Visualization recommendations","Executive summaries","Actionable insights"],
    "input_schema": {
        "type": "object",
        "properties": {
            "data_or_topic":  {"type": "string", "description": "Data, text, or topic to analyze"},
            "analysis_type":  {"type": "string", "enum": ["insights","swot","trends","competitive","full"], "default": "full"},
            "output_format":  {"type": "string", "enum": ["executive","detailed","bullets"],                "default": "detailed"}
        },
        "required": ["data_or_topic"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "executive_summary":        {"type": "string"},
            "key_insights":             {"type": "array", "items": {"type": "string"}},
            "recommendations":          {"type": "array", "items": {"type": "string"}},
            "risk_factors":             {"type": "array", "items": {"type": "string"}},
            "visualization_suggestions":{"type": "array", "items": {"type": "string"}}
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
        "can_receive_from": ["research-agent-001","writer-agent-002"],
        "input_keys":       ["research_context","written_content"],
        "output_key":       "analysis_result",
        "typical_pipeline": "research → analyst  OR  research → writer → analyst"
    }
}

app = FastAPI(title="AnalystBot Agent", version="1.0.0", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ExecuteRequest(BaseModel):
    data_or_topic: str
    analysis_type: str            = "full"
    output_format: str            = "detailed"
    context:       Optional[dict] = None


# ── CORE LOGIC FUNCTION (same pattern as research1.py) ─────────────────────────
async def run_agent_logic(req: ExecuteRequest, api_key: str):
    upstream_data = ""
    if req.context:
        if "research_context" in req.context:
            rc = req.context["research_context"]
            upstream_data += (
                f"\n\n[Research Agent Output]\n"
                f"Title: {rc.get('title','')}\n"
                f"Summary: {rc.get('summary','')}\n"
                f"Findings: {'; '.join(rc.get('key_findings',[]))}"
            )
        if "written_content" in req.context:
            wc = req.context["written_content"]
            upstream_data += (
                f"\n\n[Writer Agent Output]\n"
                f"Title: {wc.get('title','')}\n"
                f"Content Preview: {str(wc.get('content',''))[:500]}..."
            )

    analysis_instructions = {
        "insights":    "Focus on extracting 5-7 sharp, non-obvious insights.",
        "swot":        "Produce a thorough SWOT analysis.",
        "trends":      "Identify key trends and forecast directions.",
        "competitive": "Perform a competitive landscape analysis.",
        "full":        "Provide comprehensive analysis: insights, SWOT, trends, risks, and recommendations."
    }

    system_prompt = (
        f"You are AnalystBot, a razor-sharp data analyst. "
        f"{analysis_instructions.get(req.analysis_type, analysis_instructions['full'])} "
        f"Format: {req.output_format}. "
        f"Return JSON with keys: executive_summary (string), key_insights (array of strings), "
        f"recommendations (array of strings), risk_factors (array of strings), "
        f"visualization_suggestions (array of strings)."
    )
    user_prompt = f"Analyze: {req.data_or_topic}{upstream_data}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

    async with httpx.AsyncClient() as client:
        resp = await post_chat(client, api_key, messages, timeout=60)

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=format_llm_http_error(resp))

    content = resp.json()["choices"][0]["message"]["content"]

    try:
        result = json.loads(content)
    except Exception:
        result = {
            "executive_summary":         content,
            "key_insights":              [],
            "recommendations":           [],
            "risk_factors":              [],
            "visualization_suggestions": []
        }

    return {
        "agent_id": AGENT_CARD["agent_id"],
        "status":   "success",
        "result":   result,
        "a2a_passthrough": {
            "analysis_result": result,
            "original_topic":  req.data_or_topic
        }
    }


@app.get("/.well-known/agent.json")
async def get_agent_card():
    return AGENT_CARD

@app.get("/health")
async def health():
    return {"status": "ok", "agent": AGENT_CARD["agent_id"]}


@app.post("/a2a/execute")
async def execute(
    req: ExecuteRequest,
    authorization:        Optional[str] = Header(None),
    x_agent_token:        Optional[str] = Header(None),
    x_openrouter_api_key: Optional[str] = Header(None, alias="X-OpenRouter-API-Key"),
):
    # Auth: internal orchestrator token OR user JWT
    if x_agent_token:
        verify_internal_agent_token(AGENT_TOKEN, x_agent_token)

    elif authorization:
        user = verify_user_jwt(authorization)

        # PURCHASE CHECK
        agent_id = "analyst-agent-003"
        if agent_id not in user.get("purchased_agents", []):
            raise HTTPException(status_code=403, detail="Buy agent first")

    else:
        raise HTTPException(status_code=401, detail="Authentication required")

    api_key = (x_openrouter_api_key or "").strip() or resolve_env_api_key()
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing LLM API key")

    # ── INPUT GUARDRAILS ──────────────────────────────────────────────────────
    topic = req.data_or_topic.strip()

    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty. Please enter a topic to analyze.")
    if len(topic) < 3:
        raise HTTPException(status_code=400, detail="Topic is too short. Please enter at least 3 characters.")
    if len(topic) > 2000:
        raise HTTPException(status_code=400, detail="Topic is too long (max 2000 characters).")
    if (topic.startswith("gsk_") or topic.startswith("sk-or-v1-") or
            topic.startswith("sk-") or topic.startswith("Bearer ")):
        raise HTTPException(status_code=400, detail="Invalid input: please enter a topic to analyze, not an API key.")

    import re as _re
    if not _re.search(r"[a-zA-Z0-9]", topic):
        raise HTTPException(status_code=400, detail="Topic must contain letters or numbers.")

    _BLOCKED = [
        "ignore previous instructions", "ignore all instructions",
        "disregard the above", "forget everything", "jailbreak",
        "you are now", "act as ", "pretend you are",
        "override instructions", "\n\nsystem:", "\\n\\nsystem:"
    ]
    tl = topic.lower()
    for pat in _BLOCKED:
        if pat in tl:
            raise HTTPException(status_code=400, detail="Input contains disallowed content.")
    # ─────────────────────────────────────────────────────────────────────────

    return await run_agent_logic(req, api_key)


@app.get("/a2a/execute")
async def execute_get(
    data_or_topic: str = None,
    analysis_type: str = "full",
    output_format: str = "detailed"
):
    # No topic → show UI (same pattern as research1.py)
    if not data_or_topic:
        return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AnalystBot</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f7; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 40px 16px; }
    .card { background: white; border-radius: 16px; box-shadow: 0 2px 20px rgba(0,0,0,0.08); padding: 32px; width: 100%; max-width: 600px; margin-bottom: 24px; }
    h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; display: flex; align-items: center; gap: 10px; }
    .sub { font-size: 13px; color: #888; margin-bottom: 24px; }
    label { display: block; font-size: 13px; font-weight: 600; color: #333; margin-bottom: 6px; }
    textarea { width: 100%; border: 1.5px solid #e0e0e0; border-radius: 8px; padding: 10px 12px; font-size: 14px; font-family: inherit; resize: vertical; min-height: 90px; outline: none; transition: border-color .2s; }
    textarea:focus { border-color: #6c63ff; }
    select { width: 100%; border: 1.5px solid #e0e0e0; border-radius: 8px; padding: 9px 12px; font-size: 14px; font-family: inherit; outline: none; background: white; cursor: pointer; }
    select:focus { border-color: #6c63ff; }
    .form-group { margin-bottom: 16px; }
    .row { display: flex; gap: 12px; }
    .row .form-group { flex: 1; }
    button { width: 100%; background: #6c63ff; color: white; border: none; border-radius: 10px; padding: 13px; font-size: 15px; font-weight: 600; cursor: pointer; margin-top: 4px; transition: background .2s; }
    button:hover { background: #5a52e0; }
    button:disabled { background: #b0adee; cursor: not-allowed; }
    .result { background: white; border-radius: 16px; box-shadow: 0 2px 20px rgba(0,0,0,0.08); width: 100%; max-width: 600px; overflow: hidden; }
    .result-header { background: #1a1a2e; color: white; padding: 14px 20px; font-weight: 600; font-size: 14px; }
    .result-body { padding: 20px; }
    .section { margin-bottom: 20px; }
    .section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #6c63ff; margin-bottom: 8px; }
    .text { font-size: 14px; color: #333; line-height: 1.6; }
    .list-item { display: flex; gap: 8px; font-size: 14px; color: #333; line-height: 1.5; padding: 5px 0; border-bottom: 1px solid #f0f0f0; }
    .list-item:last-child { border-bottom: none; }
    .bullet { color: #6c63ff; font-weight: 700; flex-shrink: 0; }
    .bullet.tip { color: #22c55e; }
    .bullet.warn { color: #f59e0b; }
    .placeholder { color: #aaa; font-size: 14px; text-align: center; padding: 24px; }
    .loading { display: none; text-align: center; padding: 24px; color: #6c63ff; font-size: 14px; }
    .loading.active { display: block; }
    .spinner { display: inline-block; width: 20px; height: 20px; border: 3px solid #e0e0e0; border-top-color: #6c63ff; border-radius: 50%; animation: spin .7s linear infinite; margin-bottom: 8px; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="card">
    <h1>📊 AnalystBot</h1>
    <div class="sub">Data analyst agent · SWOT · Trends · Insights · Recommendations</div>
    <div class="form-group">
      <label>Topic / Data to Analyze</label>
      <textarea id="topic" placeholder="e.g. Electric vehicle market in 2025"></textarea>
    </div>
    <div class="row">
      <div class="form-group">
        <label>Analysis Type</label>
        <select id="atype">
          <option value="full" selected>Full Analysis</option>
          <option value="insights">Insights Only</option>
          <option value="swot">SWOT</option>
          <option value="trends">Trends</option>
          <option value="competitive">Competitive</option>
        </select>
      </div>
      <div class="form-group">
        <label>Output Format</label>
        <select id="aformat">
          <option value="detailed" selected>Detailed</option>
          <option value="executive">Executive</option>
          <option value="bullets">Bullets</option>
        </select>
      </div>
    </div>
    <button id="runBtn" onclick="runAgent()">&#9658; Run AnalystBot</button>
  </div>

  <div class="loading" id="loading">
    <div class="spinner"></div><br>Running analysis...
  </div>

  <div class="result" id="resultBox">
    <div class="result-header">📊 AnalystBot — Results</div>
    <div class="result-body" id="resultBody">
      <div class="placeholder">Run the agent to see results...</div>
    </div>
  </div>

  <script>
    function esc(s) {
      const d = document.createElement('div');
      d.textContent = String(s || '');
      return d.innerHTML;
    }
    async function runAgent() {
      const topic = document.getElementById('topic').value.trim();
      if (!topic) { alert('Please enter a topic or data to analyze.'); return; }
      document.getElementById('runBtn').disabled = true;
      document.getElementById('loading').classList.add('active');
      document.getElementById('resultBody').innerHTML = '';
      try {
        const res = await fetch(
          '?data_or_topic=' + encodeURIComponent(topic) +
          '&analysis_type=' + document.getElementById('atype').value +
          '&output_format=' + document.getElementById('aformat').value
        );
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
        const r = data.result;
        let h = '';
        if (r.executive_summary)              h += `<div class="section"><div class="section-title">Executive Summary</div><div class="text">${esc(r.executive_summary)}</div></div>`;
        if (r.key_insights?.length)           h += `<div class="section"><div class="section-title">Key Insights</div>${r.key_insights.map(i=>`<div class="list-item"><span class="bullet">&#9670;</span>${esc(i)}</div>`).join('')}</div>`;
        if (r.recommendations?.length)        h += `<div class="section"><div class="section-title">Recommendations</div>${r.recommendations.map(i=>`<div class="list-item"><span class="bullet tip">&#8594;</span>${esc(i)}</div>`).join('')}</div>`;
        if (r.risk_factors?.length)           h += `<div class="section"><div class="section-title">Risk Factors</div>${r.risk_factors.map(i=>`<div class="list-item"><span class="bullet warn">&#9888;</span>${esc(i)}</div>`).join('')}</div>`;
        if (r.visualization_suggestions?.length) h += `<div class="section"><div class="section-title">Visualization Suggestions</div>${r.visualization_suggestions.map(i=>`<div class="list-item"><span class="bullet" style="color:#888">&#128200;</span>${esc(i)}</div>`).join('')}</div>`;
        document.getElementById('resultBody').innerHTML = h || '<div class="placeholder">No structured result returned.</div>';
      } catch(e) {
        document.getElementById('resultBody').innerHTML = `<div class="text" style="color:#e53e3e">Error: ${esc(e.message)}</div>`;
      } finally {
        document.getElementById('runBtn').disabled = false;
        document.getElementById('loading').classList.remove('active');
      }
    }
  </script>
</body>
</html>""")

    # Topic provided → run agent logic (same pattern as research1.py)
    try:
        req = ExecuteRequest(
            data_or_topic=data_or_topic,
            analysis_type=analysis_type,
            output_format=output_format
        )
        api_key = resolve_env_api_key()
        if not api_key:
            raise HTTPException(status_code=401, detail="Missing API key")
        return await run_agent_logic(req, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/a2a/status")
async def status():
    return {"agent_id": AGENT_CARD["agent_id"], "status": "ready", "load": "low"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)