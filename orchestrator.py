"""
A2A Orchestrator Service
Handles multi-agent pipelines — only accessible to authenticated users.
JWT is verified here; internal agent tokens are kept server-side only.
"""

import json
import os
import inspect
import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uvicorn

from llm_client import verify_user_jwt

app = FastAPI(title="A2A Orchestrator", version="1.0.0", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Agent registry — internal tokens are read from ENV, never from client ─────
AGENT_REGISTRY = {
    "research-agent-001": {
        "base_url": "http://127.0.0.1:8001",
        "token":    os.environ.get("AGENT_TOKEN_RESEARCH", "research-token-abc123"),
        "card_url": "http://127.0.0.1:8001/.well-known/agent.json"
    },
    "writer-agent-002": {
        "base_url": "http://127.0.0.1:8002",
        "token":    os.environ.get("AGENT_TOKEN_WRITER", "writer-token-def456"),
        "card_url": "http://127.0.0.1:8002/.well-known/agent.json"
    },
    "analyst-agent-003": {
        "base_url": "http://127.0.0.1:8003",
        "token":    os.environ.get("AGENT_TOKEN_ANALYST", "analyst-token-ghi789"),
        "card_url": "http://127.0.0.1:8003/.well-known/agent.json"
    }
}

PIPELINE_TEMPLATES = {
    frozenset(["research-agent-001", "writer-agent-002"]): {
        "name": "Research → Write",
        "description": "Deep research feeds directly into content creation",
        "steps": ["research-agent-001", "writer-agent-002"],
        "input_mapping": {
            "research-agent-001": lambda ui: {
                "query": ui.get("topic", ui.get("query", "")),
                "depth": ui.get("depth", "standard"),
                "format": "report"
            },
            "writer-agent-002": lambda ui, prev: {
                "topic":        ui.get("topic", ui.get("query", "")),
                "style":        ui.get("style", "professional"),
                "length":       ui.get("length", "medium"),
                "content_type": ui.get("content_type", "blog"),
                "context":      prev.get("a2a_passthrough", {})
            }
        }
    },
    frozenset(["research-agent-001", "analyst-agent-003"]): {
        "name": "Research → Analyze",
        "description": "Research feeds into deep analytical insights",
        "steps": ["research-agent-001", "analyst-agent-003"],
        "input_mapping": {
            "research-agent-001": lambda ui: {
                "query": ui.get("topic", ui.get("query", "")),
                "depth": "deep",
                "format": "report"
            },
            "analyst-agent-003": lambda ui, prev: {
                "data_or_topic": ui.get("topic", ui.get("query", "")),
                "analysis_type": ui.get("analysis_type", "full"),
                "output_format": "detailed",
                "context":       prev.get("a2a_passthrough", {})
            }
        }
    },
    frozenset(["writer-agent-002", "analyst-agent-003"]): {
        "name": "Write → Analyze",
        "description": "Written content gets analyzed for quality and insights",
        "steps": ["writer-agent-002", "analyst-agent-003"],
        "input_mapping": {
            "writer-agent-002": lambda ui: {
                "topic":        ui.get("topic", ""),
                "style":        ui.get("style", "professional"),
                "length":       ui.get("length", "medium"),
                "content_type": ui.get("content_type", "blog")
            },
            "analyst-agent-003": lambda ui, prev: {
                "data_or_topic": ui.get("topic", ""),
                "analysis_type": "insights",
                "output_format": "detailed",
                "context":       prev.get("a2a_passthrough", {})
            }
        }
    },
    frozenset(["research-agent-001", "writer-agent-002", "analyst-agent-003"]): {
        "name": "Research → Write → Analyze",
        "description": "Full pipeline: research feeds writing, then everything gets analyzed",
        "steps": ["research-agent-001", "writer-agent-002", "analyst-agent-003"],
        "input_mapping": {
            "research-agent-001": lambda ui: {
                "query": ui.get("topic", ui.get("query", "")),
                "depth": ui.get("depth", "deep"),
                "format": "report"
            },
            "writer-agent-002": lambda ui, prev: {
                "topic":        ui.get("topic", ui.get("query", "")),
                "style":        ui.get("style", "professional"),
                "length":       ui.get("length", "medium"),
                "content_type": ui.get("content_type", "blog"),
                "context":      prev.get("a2a_passthrough", {})
            },
            "analyst-agent-003": lambda ui, prev: {
                "data_or_topic": ui.get("topic", ui.get("query", "")),
                "analysis_type": "full",
                "output_format": "detailed",
                "context":       prev.get("a2a_passthrough", {})
            }
        }
    }
}


class OrchestrateRequest(BaseModel):
    agent_ids:  List[str]
    user_input: Dict[str, Any]
    user_id:    str

class SingleAgentRequest(BaseModel):
    agent_id:   str
    user_input: Dict[str, Any]
    user_id:    str


async def discover_agent_card(agent_id: str) -> dict:
    agent = AGENT_REGISTRY.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    async with httpx.AsyncClient() as client:
        resp = await client.get(agent["card_url"], timeout=10)
        if resp.status_code == 200:
            return resp.json()
    return {}


async def call_agent(
    agent_id:        str,
    payload:         dict,
    openrouter_key:  Optional[str] = None,
) -> dict:
    """
    Calls an agent using its internal X-Agent-Token.
    The token is NEVER sent to the browser — only server-to-server.
    """
    agent = AGENT_REGISTRY[agent_id]
    headers = {
        "X-Agent-Token": agent["token"],   # internal token — hidden from browser
        "Content-Type":  "application/json",
    }
    if openrouter_key:
        headers["X-OpenRouter-API-Key"] = openrouter_key

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{agent['base_url']}/a2a/execute",
            headers=headers,
            json=payload,
            timeout=90
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Agent {agent_id} failed: {resp.text}")
    return resp.json()


@app.post("/orchestrate")
async def orchestrate(
    req: OrchestrateRequest,
    user:                 dict = Depends(verify_user_jwt),   # ← JWT required
    x_openrouter_api_key: Optional[str] = Header(None, alias="X-OpenRouter-API-Key"),
):
    agent_set = frozenset(req.agent_ids)
    pipeline  = None
    for key, tmpl in PIPELINE_TEMPLATES.items():
        if key == agent_set:
            pipeline = tmpl
            break

    if not pipeline:
        pipeline = {
            "name":          "Custom Pipeline",
            "steps":         req.agent_ids,
            "input_mapping": {aid: (lambda u: u) for aid in req.agent_ids}
        }

    steps_results          = []
    prev_output            = None
    accumulated_passthrough = {}

    for step_agent_id in pipeline["steps"]:
        card        = await discover_agent_card(step_agent_id)
        mapping_fn  = pipeline["input_mapping"].get(step_agent_id)

        if mapping_fn:
            sig = inspect.signature(mapping_fn)
            if len(sig.parameters) == 1:
                payload = mapping_fn(req.user_input)
            else:
                payload = mapping_fn(req.user_input, prev_output or {})
        else:
            payload = req.user_input

        if "context" in payload and isinstance(payload["context"], dict):
            payload["context"].update(accumulated_passthrough)
        elif accumulated_passthrough:
            payload["context"] = accumulated_passthrough

        result = await call_agent(step_agent_id, payload, x_openrouter_api_key)

        if "a2a_passthrough" in result:
            accumulated_passthrough.update(result["a2a_passthrough"])

        steps_results.append({
            "agent_id":   step_agent_id,
            "agent_name": card.get("name", step_agent_id),
            "agent_icon": card.get("icon", "🤖"),
            "result":     result.get("result", {}),
            "status":     result.get("status", "unknown")
        })
        prev_output = result

    return {
        "pipeline_name":       pipeline["name"],
        "agents_used":         req.agent_ids,
        "steps":               steps_results,
        "final_output":        steps_results[-1]["result"] if steps_results else {},
        "accumulated_context": accumulated_passthrough
    }


@app.post("/single")
async def single_agent(
    req:                  SingleAgentRequest,
    user:                 dict = Depends(verify_user_jwt),
    x_openrouter_api_key: Optional[str] = Header(None, alias="X-OpenRouter-API-Key"),
):
    card   = await discover_agent_card(req.agent_id)
    result = await call_agent(req.agent_id, req.user_input, openrouter_key=x_openrouter_api_key)
    return {
        "pipeline_name": f"Single: {card.get('name', req.agent_id)}",
        "agents_used":   [req.agent_id],
        "steps":         [{
            "agent_id":   req.agent_id,
            "agent_name": card.get("name", req.agent_id),
            "agent_icon": card.get("icon", "🤖"),
            "result":     result.get("result", {}),
            "status":     result.get("status", "unknown")
        }],
        "final_output":  result.get("result", {})
    }


@app.get("/pipelines")
async def list_pipelines(user: dict = Depends(verify_user_jwt)):
    return {"pipelines": [
        {
            "agents":      list(agent_set),
            "name":        tmpl["name"],
            "description": tmpl["description"],
            "steps":       tmpl["steps"]
        }
        for agent_set, tmpl in PIPELINE_TEMPLATES.items()
    ]}


@app.get("/agents/{agent_id}/card")
async def get_agent_card(agent_id: str, user: dict = Depends(verify_user_jwt)):
    return await discover_agent_card(agent_id)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
