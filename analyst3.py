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

async def run_agent_logic(req: ExecuteRequest, api_key: str):

    upstream_data = ""
    if req.context:
        if "research_context" in req.context:
            rc = req.context["research_context"]
            upstream_data += f"\nResearch: {rc.get('summary','')}"
        if "written_content" in req.context:
            wc = req.context["written_content"]
            upstream_data += f"\nWritten: {wc.get('content','')[:300]}"

    analysis_instructions = {
        "insights": "Give key insights",
        "swot": "Do SWOT analysis",
        "trends": "Find trends",
        "competitive": "Do competitive analysis",
        "full": "Full deep analysis"
    }

    system_prompt = (
        f"You are AnalystBot. {analysis_instructions.get(req.analysis_type)} "
        f"Format: {req.output_format}. "
        f"Return JSON with executive_summary, key_insights, recommendations."
    )

    user_prompt = f"Analyze: {req.data_or_topic}{upstream_data}"

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
            "executive_summary": content,
            "key_insights": [],
            "recommendations": []
        }

    return {
        "agent_id": AGENT_CARD["agent_id"],
        "status": "success",
        "result": result
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
    if x_agent_token:
        verify_internal_agent_token(AGENT_TOKEN, x_agent_token)

    elif authorization:
        user = verify_user_jwt(authorization)

        # ✅ PURCHASE CHECK
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

    # 1. Empty input
    if not topic:
        raise HTTPException(status_code=400, detail="Input cannot be empty. Please enter a topic or data to analyze.")

    # 2. Too short
    if len(topic) < 3:
        raise HTTPException(status_code=400, detail="Input is too short. Please enter at least 3 characters.")

    # 3. Too long
    if len(topic) > 2000:
        raise HTTPException(status_code=400, detail="Input is too long (max 2000 characters).")

    # 4. Input looks like an API key
    if (topic.startswith("gsk_") or topic.startswith("sk-or-v1-") or
            topic.startswith("sk-") or topic.startswith("Bearer ")):
        raise HTTPException(status_code=400, detail="Invalid input: please enter a topic or data, not an API key.")

    # 5. No real alphanumeric content
    import re as _re
    if not _re.search(r"[a-zA-Z0-9]", topic):
        raise HTTPException(status_code=400, detail="Input must contain letters or numbers.")

    # 6. Prompt injection patterns
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
async def execute_get(data_or_topic: str = None, analysis_type: str = "full", output_format: str = "detailed"):

    if not data_or_topic:
        return HTMLResponse("""
<html>
<head>
    <title>AnalystBot</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #f5f7fb; padding: 40px; }
        .container { max-width: 800px; margin: auto; }
        .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); margin-bottom: 20px; }
        h2 { margin-bottom: 15px; }
        textarea { width: 100%; height: 80px; padding: 10px; border-radius: 8px; border: 1px solid #ccc; }
        select { width: 100%; padding: 10px; margin-top: 10px; border-radius: 8px; border: 1px solid #ccc; }
        button { margin-top: 15px; padding: 12px; width: 100%; background: #4f6bed; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; }
        button:hover { background: #3d55c4; }
        .section-title { font-weight: bold; margin-top: 15px; margin-bottom: 5px; }
        ul { padding-left: 20px; }
        li { margin-bottom: 6px; line-height: 1.6; }
    </style>
</head>
<body>
<div class="container">
    <div class="card">
        <h2>📊 AnalystBot</h2>
        <label>Topic / Data to Analyze</label>
        <textarea id="topic">AI market trends</textarea>
        <label>Analysis Type</label>
        <select id="atype">
            <option value="full" selected>Full Analysis</option>
            <option value="insights">Insights Only</option>
            <option value="swot">SWOT</option>
            <option value="trends">Trends</option>
            <option value="competitive">Competitive</option>
        </select>
        <label>Output Format</label>
        <select id="format">
            <option value="detailed" selected>Detailed</option>
            <option value="executive">Executive</option>
            <option value="bullets">Bullets</option>
        </select>
        <button onclick="run()">▶ Run AnalystBot</button>
    </div>
    <div class="card" id="output"><p>Run the agent to see results...</p></div>
</div>
<script>
window.run = async function() {
    const output = document.getElementById("output");
    output.innerHTML = "<p>⏳ Running agent...</p>";
    const topic = document.getElementById("topic").value;
    const atype = document.getElementById("atype").value;
    const fmt = document.getElementById("format").value;
    try {
        const baseUrl = window.location.origin + window.location.pathname;
        const res = await fetch(baseUrl + "?data_or_topic=" + encodeURIComponent(topic) + "&analysis_type=" + atype + "&output_format=" + fmt);
        const data = await res.json();
        const result = data.result || {};
        function toStr(v) {
            if (!v) return "";
            if (typeof v === "string") return v;
            if (typeof v === "number" || typeof v === "boolean") return String(v);
            if (Array.isArray(v)) return v.map(toStr).filter(Boolean).join("\n");
            if (typeof v === "object") {
                // Extract all string values from nested object into readable lines
                var parts = [];
                for (var k in v) {
                    if (!v.hasOwnProperty(k)) continue;
                    var val = v[k];
                    var label = k.replace(/_/g, " ").replace(/\b\w/g, function(c){ return c.toUpperCase(); });
                    if (typeof val === "string" && val.trim()) {
                        parts.push(label + ": " + val.trim());
                    } else if (Array.isArray(val)) {
                        parts.push(label + ": " + val.map(toStr).join(", "));
                    }
                }
                return parts.length ? parts.join("\n") : JSON.stringify(v, null, 2);
            }
            return String(v);
        }
        function toArr(v) {
            if (!v) return [];
            if (Array.isArray(v)) return v;
            if (typeof v === "string") return v.split("\n").filter(Boolean);
            return [v];
        }
        const summary = toStr(result.executive_summary) || "No summary available";
        const insights = toArr(result.key_insights).map(i => "<li>" + toStr(i) + "</li>").join("");
        const recs = toArr(result.recommendations).map(i => "<li>" + toStr(i) + "</li>").join("");
        const risks = toArr(result.risk_factors).map(i => "<li>" + toStr(i) + "</li>").join("");
        const viz = toArr(result.visualization_suggestions).map(i => "<li>" + toStr(i) + "</li>").join("");
        output.innerHTML =
            "<div class='section-title'>Executive Summary</div><p>" + summary + "</p>" +
            (insights ? "<div class='section-title'>Key Insights</div><ul>" + insights + "</ul>" : "") +
            (recs ? "<div class='section-title'>Recommendations</div><ul>" + recs + "</ul>" : "") +
            (risks ? "<div class='section-title'>Risk Factors</div><ul>" + risks + "</ul>" : "") +
            (viz ? "<div class='section-title'>Visualization Suggestions</div><ul>" + viz + "</ul>" : "");
    } catch (e) {
        output.innerHTML = "<p style='color:red;'>Error: " + e.message + "</p>";
    }
};
</script>
</body>
</html>
        """)

    req = ExecuteRequest(data_or_topic=data_or_topic, analysis_type=analysis_type, output_format=output_format)

    api_key = resolve_env_api_key()
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    try:
        return await run_agent_logic(req, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/a2a/status")
async def status():
    return {"agent_id": AGENT_CARD["agent_id"], "status": "ready", "load": "low"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)