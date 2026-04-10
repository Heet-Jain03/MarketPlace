"""
Agent 2: Writer Agent
AgentCard-based A2A compliant agent for content writing and copywriting
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
    "agent_id": "writer-agent-002",
    "name": "WriteBot",
    "version": "1.0.0",
    "description": "A professional content writing agent that creates blog posts, articles, marketing copy, social media content, and technical documentation in any tone or style.",
    "author": "AgentMarketplace",
    "icon": "✍️",
    "price_usd": 7.99,
    "category": "Writing & Content",
    "capabilities": [
        "Blog posts & articles",
        "Marketing copywriting",
        "Social media content",
        "Technical documentation",
        "Email campaigns",
        "SEO-optimized writing"
    ],
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "What to write about"},
            "style": {"type": "string", "enum": ["professional", "casual", "academic", "creative", "marketing"], "default": "professional"},
            "length": {"type": "string", "enum": ["short", "medium", "long"], "default": "medium"},
            "content_type": {"type": "string", "enum": ["blog", "social", "email", "doc", "ad_copy"], "default": "blog"}
        },
        "required": ["topic"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "word_count": {"type": "integer"},
            "meta_description": {"type": "string"}
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
        "can_receive_from": ["research-agent-001"],
        "can_feed_into": ["analyst-agent-003"],
        "input_key": "research_context",
        "output_key": "written_content",
        "typical_pipeline": "research → writer → analyst"
    }
}

AGENT_TOKEN = "writer-token-def456"

app = FastAPI(title="WriteBot Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ExecuteRequest(BaseModel):
    topic: str
    style: str = "professional"
    length: str = "medium"
    content_type: str = "blog"
    context: Optional[dict] = None  # A2A passthrough from ResearchBot

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

    length_map = {"short": "300-400 words", "medium": "600-800 words", "long": "1200-1500 words"}

    # If context from ResearchBot is present, use it
    research_context = ""
    if req.context and "research_context" in req.context:
        rc = req.context["research_context"]
        research_context = f"\n\nUse this research as your factual foundation:\nTitle: {rc.get('title','')}\nSummary: {rc.get('summary','')}\nKey Findings: {'; '.join(rc.get('key_findings',[]))}"

    system_prompt = f"""You are WriteBot, an expert content writer.
    Write a {style_desc(req.style)} {req.content_type} of {length_map[req.length]}.
    Return JSON with keys: title, content, word_count (integer), meta_description."""

    user_prompt = f"Write about: {req.topic}{research_context}"

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
        result = {"title": req.topic, "content": content, "word_count": len(content.split()), "meta_description": ""}

    return {
        "agent_id": AGENT_CARD["agent_id"],
        "status": "success",
        "result": result,
        "a2a_passthrough": {
            "written_content": result,
            "original_topic": req.topic
        }
    }

def style_desc(style: str) -> str:
    styles = {
        "professional": "polished and professional",
        "casual": "conversational and friendly",
        "academic": "scholarly and rigorous",
        "creative": "creative and engaging",
        "marketing": "persuasive and compelling"
    }
    return styles.get(style, "professional")

@app.get("/a2a/status")
async def status():
    return {"agent_id": AGENT_CARD["agent_id"], "status": "ready", "load": "low"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)