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

async def run_agent_logic(req: ExecuteRequest, api_key: str):

    length_map = {"short": "300-400 words", "medium": "600-800 words", "long": "1200-1500 words"}

    system_prompt = (
        f"You are WriteBot. Write {req.content_type} in {req.style} style of {length_map.get(req.length)}. "
        f"Return JSON with keys: title, content, word_count, meta_description."
    )

    user_prompt = f"Write about: {req.topic}"

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
            "title": req.topic,
            "content": content,
            "word_count": len(content.split()),
            "meta_description": ""
        }

    return {
        "agent_id": AGENT_CARD["agent_id"],
        "status": "success",
        "result": result
    }




def style_desc(style: str) -> str:
    return {"professional":"polished and professional","casual":"conversational and friendly",
            "academic":"scholarly and rigorous","creative":"creative and engaging",
            "marketing":"persuasive and compelling"}.get(style, "professional")


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

    # 1. Empty input
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty. Please enter a writing topic.")

    # 2. Too short
    if len(topic) < 3:
        raise HTTPException(status_code=400, detail="Topic is too short. Please enter at least 3 characters.")

    # 3. Too long
    if len(topic) > 2000:
        raise HTTPException(status_code=400, detail="Topic is too long (max 2000 characters).")

    # 4. Input looks like an API key
    if (topic.startswith("gsk_") or topic.startswith("sk-or-v1-") or
            topic.startswith("sk-") or topic.startswith("Bearer ")):
        raise HTTPException(status_code=400, detail="Invalid input: please enter a writing topic, not an API key.")

    # 5. No real alphanumeric content
    import re as _re
    if not _re.search(r"[a-zA-Z0-9]", topic):
        raise HTTPException(status_code=400, detail="Topic must contain letters or numbers.")

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
async def execute_get(topic: str = None, style: str = "professional", length: str = "medium", content_type: str = "blog"):

    if not topic:
        return HTMLResponse("""
        <html>
        <body>
        <h2>✍️ WriteBot</h2>

        <textarea id="topic">AI future</textarea><br>

        <select id="style">
            <option value="professional">Professional</option>
            <option value="casual">Casual</option>
        </select><br>

        <select id="length">
            <option value="short">Short</option>
            <option value="medium" selected>Medium</option>
            <option value="long">Long</option>
        </select><br>

        <button onclick="run()">Run</button>

        <div id="output"></div>

        <script>
        async function run() {
            const topic = document.getElementById("topic").value;
            const style = document.getElementById("style").value;
            const length = document.getElementById("length").value;

            const content_type = "blog";

            try {
                const res = await fetch(`?topic=${encodeURIComponent(topic)}&style=${style}&length=${length}&content_type=${content_type}`);
                const data = await res.json();

                const result = data.result || {};

                const title = result.title || "No title";
                const content = result.content || "No content generated";

                document.getElementById("output").innerHTML =
                    "<h3>" + title + "</h3>" +
                    "<p>" + content + "</p>";

            } catch (e) {
                document.getElementById("output").innerHTML =
                    "<p style='color:red;'>Error: Failed to fetch response</p>";
}
        </script>

        </body>
        </html>
        """)

    req = ExecuteRequest(topic=topic, style=style, length=length, content_type=content_type)

    api_key = resolve_env_api_key()
    return await run_agent_logic(req, api_key)

@app.get("/a2a/status")
async def status():
    return {"agent_id": AGENT_CARD["agent_id"], "status": "ready", "load": "low"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)