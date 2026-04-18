"""
Agent 2: Writer Agent
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

AGENT_TOKEN = os.environ.get("AGENT_TOKEN_WRITER", "writer-token-def456")

AGENT_CARD = {
    "schema_version": "1.0",
    "agent_id":       "writer-agent-002",
    "name":           "WriteBot",
    "version":        "1.0.0",
    "description":    "A professional content writing agent that creates blog posts, articles, marketing copy, social media content, and technical documentation in any tone or style.",
    "author":         "AgentMarketplace",
    "icon":           "✍️",
    "price_usd":      7.99,
    "category":       "Writing & Content",
    "capabilities":   ["Blog posts & articles","Marketing copywriting","Social media content","Technical documentation","Email campaigns","SEO-optimized writing"],
    "input_schema": {
        "type": "object",
        "properties": {
            "topic":        {"type": "string", "description": "What to write about"},
            "style":        {"type": "string", "enum": ["professional","casual","academic","creative","marketing"], "default": "professional"},
            "length":       {"type": "string", "enum": ["short","medium","long"],                                  "default": "medium"},
            "content_type": {"type": "string", "enum": ["blog","social","email","doc","ad_copy"],                  "default": "blog"}
        },
        "required": ["topic"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "title":            {"type": "string"},
            "content":          {"type": "string"},
            "word_count":       {"type": "integer"},
            "meta_description": {"type": "string"}
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
        "can_receive_from": ["research-agent-001"],
        "can_feed_into":    ["analyst-agent-003"],
        "input_key":        "research_context",
        "output_key":       "written_content",
        "typical_pipeline": "research → writer → analyst"
    }
}

app = FastAPI(title="WriteBot Agent", version="1.0.0", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ExecuteRequest(BaseModel):
    topic:        str
    style:        str            = "professional"
    length:       str            = "medium"
    content_type: str            = "blog"
    context:      Optional[dict] = None


# ── CORE LOGIC FUNCTION (same pattern as research1.py) ─────────────────────────
async def run_agent_logic(req: ExecuteRequest, api_key: str):
    length_map = {"short": "300-400 words", "medium": "600-800 words", "long": "1200-1500 words"}

    prior_context = ""
    if req.context:
        prior_context = f"\n\nAdditional context:\n{json.dumps(req.context, indent=2)}"

    system_prompt = (
        f"You are WriteBot. Write {req.content_type} in {req.style} style of {length_map.get(req.length, '600-800 words')}. "
        f"Return JSON with keys: title, content, word_count, meta_description."
    )
    user_prompt = f"Write about: {req.topic}{prior_context}"

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
            "title":            req.topic,
            "content":          content,
            "word_count":       len(content.split()),
            "meta_description": ""
        }

    return {
        "agent_id": AGENT_CARD["agent_id"],
        "status":   "success",
        "result":   result,
        "a2a_passthrough": {
            "written_content": result,
            "original_topic":  req.topic
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
        agent_id = "writer-agent-002"
        if agent_id not in user.get("purchased_agents", []):
            raise HTTPException(status_code=403, detail="Buy agent first")

    else:
        raise HTTPException(status_code=401, detail="Authentication required")

    api_key = (x_openrouter_api_key or "").strip() or resolve_env_api_key()
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing LLM API key")

    # ── INPUT GUARDRAILS ──────────────────────────────────────────────────────
    topic = req.topic.strip()

    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty. Please enter a writing topic.")
    if len(topic) < 3:
        raise HTTPException(status_code=400, detail="Topic is too short. Please enter at least 3 characters.")
    if len(topic) > 2000:
        raise HTTPException(status_code=400, detail="Topic is too long (max 2000 characters).")
    if (topic.startswith("gsk_") or topic.startswith("sk-or-v1-") or
            topic.startswith("sk-") or topic.startswith("Bearer ")):
        raise HTTPException(status_code=400, detail="Invalid input: please enter a writing topic, not an API key.")

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
    topic: str = None,
    style: str = "professional",
    length: str = "medium",
    content_type: str = "blog"
):
    # No topic → show UI (same pattern as research1.py)
    if not topic:
        return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WriteBot</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f7; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 40px 16px; }
    .card { background: white; border-radius: 16px; box-shadow: 0 2px 20px rgba(0,0,0,0.08); padding: 32px; width: 100%; max-width: 600px; margin-bottom: 24px; }
    h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; display: flex; align-items: center; gap: 10px; }
    .sub { font-size: 13px; color: #888; margin-bottom: 24px; }
    label { display: block; font-size: 13px; font-weight: 600; color: #333; margin-bottom: 6px; }
    textarea { width: 100%; border: 1.5px solid #e0e0e0; border-radius: 8px; padding: 10px 12px; font-size: 14px; font-family: inherit; resize: vertical; min-height: 90px; outline: none; transition: border-color .2s; }
    textarea:focus { border-color: #4f6bed; }
    select { width: 100%; border: 1.5px solid #e0e0e0; border-radius: 8px; padding: 9px 12px; font-size: 14px; font-family: inherit; outline: none; background: white; cursor: pointer; }
    select:focus { border-color: #4f6bed; }
    .form-group { margin-bottom: 16px; }
    .row { display: flex; gap: 12px; }
    .row .form-group { flex: 1; }
    button { width: 100%; background: #4f6bed; color: white; border: none; border-radius: 10px; padding: 13px; font-size: 15px; font-weight: 600; cursor: pointer; margin-top: 4px; transition: background .2s; }
    button:hover { background: #3d55c4; }
    button:disabled { background: #b0adee; cursor: not-allowed; }
    .result { background: white; border-radius: 16px; box-shadow: 0 2px 20px rgba(0,0,0,0.08); width: 100%; max-width: 600px; overflow: hidden; }
    .result-header { background: #1a1a2e; color: white; padding: 14px 20px; font-weight: 600; font-size: 14px; }
    .result-body { padding: 20px; }
    .section { margin-bottom: 20px; }
    .section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #4f6bed; margin-bottom: 8px; }
    .text { font-size: 14px; color: #333; line-height: 1.6; white-space: pre-wrap; }
    .meta { font-size: 13px; color: #666; font-style: italic; line-height: 1.5; }
    .placeholder { color: #aaa; font-size: 14px; text-align: center; padding: 24px; }
    .loading { display: none; text-align: center; padding: 24px; color: #4f6bed; font-size: 14px; }
    .loading.active { display: block; }
    .spinner { display: inline-block; width: 20px; height: 20px; border: 3px solid #e0e0e0; border-top-color: #4f6bed; border-radius: 50%; animation: spin .7s linear infinite; margin-bottom: 8px; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="card">
    <h1>✍️ WriteBot</h1>
    <div class="sub">Professional content writing agent · Blog · Social · Email · Docs</div>
    <div class="form-group">
      <label>Writing Topic</label>
      <textarea id="topic" placeholder="e.g. The future of remote work in 2025"></textarea>
    </div>
    <div class="row">
      <div class="form-group">
        <label>Style</label>
        <select id="style">
          <option value="professional" selected>Professional</option>
          <option value="casual">Casual</option>
          <option value="academic">Academic</option>
          <option value="creative">Creative</option>
          <option value="marketing">Marketing</option>
        </select>
      </div>
      <div class="form-group">
        <label>Length</label>
        <select id="length">
          <option value="short">Short</option>
          <option value="medium" selected>Medium</option>
          <option value="long">Long</option>
        </select>
      </div>
      <div class="form-group">
        <label>Content Type</label>
        <select id="ctype">
          <option value="blog" selected>Blog Post</option>
          <option value="social">Social Media</option>
          <option value="email">Email</option>
          <option value="doc">Documentation</option>
          <option value="ad_copy">Ad Copy</option>
        </select>
      </div>
    </div>
    <button id="runBtn" onclick="runAgent()">&#9658; Run WriteBot</button>
  </div>

  <div class="loading" id="loading">
    <div class="spinner"></div><br>Writing content...
  </div>

  <div class="result" id="resultBox">
    <div class="result-header">✍️ WriteBot — Results</div>
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
      if (!topic) { alert('Please enter a writing topic.'); return; }
      document.getElementById('runBtn').disabled = true;
      document.getElementById('loading').classList.add('active');
      document.getElementById('resultBody').innerHTML = '';
      try {
        const res = await fetch(
          '?topic=' + encodeURIComponent(topic) +
          '&style=' + document.getElementById('style').value +
          '&length=' + document.getElementById('length').value +
          '&content_type=' + document.getElementById('ctype').value
        );
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
        const r = data.result;
        let h = '';
        if (r.title)            h += `<div class="section"><div class="section-title">Title</div><div class="text" style="font-weight:700;font-size:15px">${esc(r.title)}</div></div>`;
        if (r.meta_description) h += `<div class="section"><div class="section-title">Meta Description</div><div class="meta">${esc(r.meta_description)}</div></div>`;
        if (r.content)          h += `<div class="section"><div class="section-title">Content${r.word_count ? ' (~' + r.word_count + ' words)' : ''}</div><div class="text">${esc(r.content)}</div></div>`;
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
        req = ExecuteRequest(topic=topic, style=style, length=length, content_type=content_type)
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
    uvicorn.run(app, host="0.0.0.0", port=8002)