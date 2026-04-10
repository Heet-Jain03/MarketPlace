"""
Agent 3: Data Analyst Agent
AgentCard-based A2A compliant agent for data analysis, insights, and visualization plans
"""

import json
import httpx
from fastapi import FastAPI, HTTPException, Header

from llm_client import format_llm_http_error, post_chat, resolve_env_api_key
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

# ── AgentCard Definition (A2A Protocol) ──────────────────────────────────────
AGENT_CARD = {
    "schema_version": "1.0",
    "agent_id": "analyst-agent-003",
    "name": "AnalystBot",
    "version": "1.0.0",
    "description": "A sharp data analyst agent that extracts insights, identifies patterns, performs SWOT analysis, generates actionable recommendations, and creates visualization blueprints from any data or content.",
    "author": "AgentMarketplace",
    "icon": "📊",
    "price_usd": 12.99,
    "category": "Data & Analytics",
    "capabilities": [
        "Data pattern recognition",
        "SWOT analysis",
        "Trend forecasting",
        "Competitive analysis",
        "Visualization recommendations",
        "Executive summaries",
        "Actionable insights"
    ],
    "input_schema": {
        "type": "object",
        "properties": {
            "data_or_topic": {"type": "string", "description": "Data, text, or topic to analyze"},
            "analysis_type": {"type": "string", "enum": ["insights", "swot", "trends", "competitive", "full"], "default": "full"},
            "output_format": {"type": "string", "enum": ["executive", "detailed", "bullets"], "default": "detailed"}
        },
        "required": ["data_or_topic"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "executive_summary": {"type": "string"},
            "key_insights": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "risk_factors": {"type": "array", "items": {"type": "string"}},
            "visualization_suggestions": {"type": "array", "items": {"type": "string"}}
        }
    },
    "a2a_endpoints": {
        "execute": "/a2a/execute",
        "status": "/a2a/status",
        "card": "/.well-known/agent.json"
    },
    "auth": {
        "type": "bearer",
        "header": "X-Agent-Token"
    },
    "orchestration_hints": {
        "can_receive_from": ["research-agent-001", "writer-agent-002"],
        "input_keys": ["research_context", "written_content"],
        "output_key": "analysis_result",
        "typical_pipeline": "research → analyst  OR  research → writer → analyst"
    }
}

AGENT_TOKEN = "analyst-token-ghi789"

app = FastAPI(title="AnalystBot Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ExecuteRequest(BaseModel):
    data_or_topic: str
    analysis_type: str = "full"
    output_format: str = "detailed"
    context: Optional[dict] = None  # A2A passthrough from Research or Writer agents

def verify_token(token: str):
    if token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid agent token")

@app.get("/.well-known/agent.json")
async def get_agent_card():
    """A2A AgentCard discovery endpoint"""
    return AGENT_CARD

@app.get("/health")
async def health():
    return {"status": "ok", "agent": AGENT_CARD["agent_id"]}

@app.post("/a2a/execute")
async def execute(
    req: ExecuteRequest,
    x_agent_token: str = Header(...),
    x_openrouter_api_key: Optional[str] = Header(None, alias="X-OpenRouter-API-Key"),
):
    verify_token(x_agent_token)
    api_key = (x_openrouter_api_key or "").strip() or resolve_env_api_key()
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key: paste Groq (gsk_…) or OpenRouter (sk-or-v1-…) in the UI and Save, or set GROQ_API_KEY / OPENROUTER_API_KEY",
        )

    # Absorb context from upstream agents (A2A chaining)
    upstream_data = ""
    if req.context:
        if "research_context" in req.context:
            rc = req.context["research_context"]
            upstream_data += f"\n\n[Research Agent Output]\nTitle: {rc.get('title','')}\nSummary: {rc.get('summary','')}\nFindings: {'; '.join(rc.get('key_findings',[]))}"
        if "written_content" in req.context:
            wc = req.context["written_content"]
            upstream_data += f"\n\n[Writer Agent Output]\nTitle: {wc.get('title','')}\nContent Preview: {str(wc.get('content',''))[:500]}..."

    analysis_instructions = {
        "insights": "Focus on extracting 5-7 sharp, non-obvious insights.",
        "swot": "Produce a thorough SWOT analysis.",
        "trends": "Identify key trends and forecast directions.",
        "competitive": "Perform a competitive landscape analysis.",
        "full": "Provide comprehensive analysis: insights, SWOT, trends, risks, and recommendations."
    }

    system_prompt = f"""You are AnalystBot, a razor-sharp data analyst. 
    {analysis_instructions.get(req.analysis_type, analysis_instructions['full'])}
    Format: {req.output_format}.
    Return JSON with keys: executive_summary, key_insights (array), recommendations (array), risk_factors (array), visualization_suggestions (array)."""

    user_prompt = f"Analyze: {req.data_or_topic}{upstream_data}"

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
            "executive_summary": content,
            "key_insights": [],
            "recommendations": [],
            "risk_factors": [],
            "visualization_suggestions": []
        }

    return {
        "agent_id": AGENT_CARD["agent_id"],
        "status": "success",
        "result": result,
        "a2a_passthrough": {
            "analysis_result": result,
            "original_topic": req.data_or_topic
        }
    }

@app.get("/a2a/status")
async def status():
    return {"agent_id": AGENT_CARD["agent_id"], "status": "ready", "load": "low"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)