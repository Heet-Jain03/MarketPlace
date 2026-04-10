"""
Shared LLM client — Groq (gsk_...) or OpenRouter (sk-or-v1-...).
Also provides JWT-based auth dependency used by all agents.
"""

from __future__ import annotations

import os
import hashlib
from typing import Any, Dict, List, Optional

import httpx
import jwt
from fastapi import Header, HTTPException

GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"

# These MUST be set via environment variables — never hardcode
JWT_SECRET      = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM   = "HS256"
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")

# Internal auth service URL (localhost only — not exposed externally)
AUTH_SERVICE_URL = os.environ.get("AUTH_SERVICE_URL", "http://127.0.0.1:8004")


def resolve_env_api_key() -> str:
    return (os.environ.get("GROQ_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or "").strip()


def infer_chat_url_and_model(api_key: str) -> tuple[str, str]:
    if api_key.startswith("gsk_"):
        model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        return GROQ_URL, model
    model = os.environ.get("OPENROUTER_MODEL", "x-ai/grok-2-mini")
    return OPENROUTER_URL, model


def chat_headers(api_key: str, url: str) -> dict[str, str]:
    h: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    if OPENROUTER_URL in url:
        h["HTTP-Referer"] = "https://agentmarketplace.local"
        h["X-Title"]      = "AgentMarketplace"
    return h


def format_llm_http_error(resp: httpx.Response) -> str:
    detail = resp.text
    try:
        body = resp.json()
        err  = body.get("error") if isinstance(body.get("error"), dict) else {}
        if err.get("message"):
            detail = str(err["message"])
        elif isinstance(body.get("error"), str):
            detail = body["error"]
    except Exception:
        pass
    prov = "Groq" if "groq.com" in str(resp.request.url) else "OpenRouter"
    return f"{prov} HTTP {resp.status_code}: {detail}"


async def post_chat(
    client: httpx.AsyncClient,
    api_key: str,
    messages: List[Dict[str, Any]],
    timeout: float = 60,
) -> httpx.Response:
    url, model = infer_chat_url_and_model(api_key)
    headers    = chat_headers(api_key, url)
    resp: Optional[httpx.Response] = None
    for use_json_object in (True, False):
        body: dict[str, Any] = {"model": model, "messages": messages}
        if use_json_object:
            body["response_format"] = {"type": "json_object"}
        resp = await client.post(url, headers=headers, json=body, timeout=timeout)
        if resp.status_code == 200:
            break
        if use_json_object and resp.status_code in (400, 422):
            continue
        break
    assert resp is not None
    return resp


# ── JWT Auth Dependency ────────────────────────────────────────────────────────
def verify_user_jwt(authorization: Optional[str] = Header(None)) -> dict:
    """
    FastAPI dependency — verifies the user's JWT access token.
    Used by all agent /a2a/execute endpoints to ensure only logged-in users run agents.
    The raw JWT is validated locally using the shared JWT_SECRET (never forwarded).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing user Authorization token")
    token = authorization.split(" ", 1)[1]
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfiguration: JWT_SECRET not set")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    return payload


def verify_internal_agent_token(expected: str, provided: str):
    """
    Verifies the internal X-Agent-Token using constant-time compare.
    These tokens are only used for service-to-service calls (orchestrator → agent).
    They are NEVER sent to the browser.
    """
    import hmac as _hmac
    if not _hmac.compare_digest(expected.encode(), provided.encode()):
        raise HTTPException(status_code=401, detail="Invalid internal agent token")
