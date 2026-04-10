"""
Agent 1: Research Agent
AgentCard-based A2A compliant agent for deep research and summarization
"""

import json
import httpx
from fastapi import FastAPI, HTTPException, Header

from llm_client import format_llm_http_error, post_chat, resolve_env_api_key
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

# ── AgentCard Definition (A2A Protocol) ──────────────────────────────────────
AGENT_CARD = {
    "schema_version": "1.0",
    "agent_id": "research-agent-001",
    "name": "ResearchBot",
    "version": "1.0.0",
    "description": "A powerful research agent that searches, synthesizes, and summarizes information on any topic. Produces structured reports with key insights.",
    "author": "AgentMarketplace",
    "icon": "🔬",
    "price_usd": 9.99,
    "category": "Research & Analysis",
    "capabilities": [
        "Deep topic research",
        "Multi-source synthesis",
        "Structured report generation",
        "Citation formatting",
        "Trend analysis"
    ],
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Research topic or question"},
            "depth": {"type": "string", "enum": ["brief", "standard", "deep"], "default": "standard"},
            "format": {"type": "string", "enum": ["bullets", "report", "summary"], "default": "report"}
        },
        "required": ["query"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "key_findings": {"type": "array", "items": {"type": "string"}},
            "raw_text": {"type": "string"}
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
        "can_feed_into": ["writer-agent-002", "analyst-agent-003"],
        "output_key": "research_context",
        "typical_pipeline": "research → writer or research → analyst"
    }
}

AGENT_TOKEN = "research-token-abc123"

app = FastAPI(title="ResearchBot Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ExecuteRequest(BaseModel):
    query: str
    depth: str = "standard"
    format: str = "report"
    context: Optional[dict] = None  # For A2A chaining from other agents

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

    depth_map = {"brief": "2-3 paragraphs", "standard": "5-6 paragraphs", "deep": "comprehensive multi-section report"}
    
    prior_context = ""
    if req.context:
        prior_context = f"\n\nAdditional context from orchestrating agent:\n{json.dumps(req.context, indent=2)}"

    system_prompt = f"""You are ResearchBot, an expert research agent. 
    Produce a {depth_map[req.depth]} research response in {req.format} format.
    Structure your response as JSON with keys: title, summary, key_findings (array of strings), raw_text."""

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
        result = {"title": req.query, "summary": content, "key_findings": [], "raw_text": content}

    return {
        "agent_id": AGENT_CARD["agent_id"],
        "status": "success",
        "result": result,
        "a2a_passthrough": {
            "research_context": result,
            "original_query": req.query
        }
    }

@app.get("/a2a/status")
async def status():
    return {"agent_id": AGENT_CARD["agent_id"], "status": "ready", "load": "low"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)