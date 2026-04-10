"""
Auth Service — JWT Authentication & Authorization
Handles: signup, login, token refresh, user management, purchased agents
Users are stored in a local SQLite DB (users.db) — no external DB needed on EC2
"""

from __future__ import annotations

import os
import re
import sqlite3
import hashlib
import hmac
import secrets
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt  # PyJWT
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
import uvicorn

# ── Config ────────────────────────────────────────────────────────────────────
JWT_SECRET       = os.environ.get("JWT_SECRET", secrets.token_hex(32))   # MUST be set via env in prod
JWT_ALGORITHM    = "HS256"
ACCESS_EXPIRE_M  = 60          # 60 minutes
REFRESH_EXPIRE_D = 7           # 7 days
DB_PATH          = os.environ.get("DB_PATH", "users.db")

# Internal service-to-service secret (never sent to browser)
INTERNAL_SECRET  = os.environ.get("INTERNAL_SECRET", secrets.token_hex(32))

# ── DB Setup ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            email       TEXT UNIQUE NOT NULL,
            username    TEXT UNIQUE NOT NULL,
            pwd_hash    TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            is_active   INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS purchased_agents (
            user_id     TEXT NOT NULL,
            agent_id    TEXT NOT NULL,
            bought_at   TEXT NOT NULL,
            price_usd   REAL NOT NULL,
            PRIMARY KEY (user_id, agent_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            token_hash  TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS rate_limit (
            ip          TEXT NOT NULL,
            endpoint    TEXT NOT NULL,
            attempts    INTEGER DEFAULT 0,
            window_start TEXT NOT NULL,
            PRIMARY KEY (ip, endpoint)
        );
    """)
    conn.commit()
    conn.close()

# ── Password Hashing ──────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000)
    return f"{salt}:{key.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, key_hex = stored.split(":", 1)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000)
        return hmac.compare_digest(key.hex(), key_hex)
    except Exception:
        return False

# ── JWT Helpers ───────────────────────────────────────────────────────────────
def create_access_token(user_id: str, email: str, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":      user_id,
        "email":    email,
        "username": username,
        "iat":      now,
        "exp":      now + timedelta(minutes=ACCESS_EXPIRE_M),
        "type":     "access",
        "jti":      secrets.token_hex(16),   # unique token ID
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> tuple[str, str]:
    """Returns (raw_token, token_hash)"""
    raw = secrets.token_urlsafe(48)
    h   = hashlib.sha256(raw.encode()).hexdigest()
    return raw, h

def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ── Rate Limiting ─────────────────────────────────────────────────────────────
RATE_LIMITS = {"/auth/login": (5, 300), "/auth/signup": (3, 600)}   # (max_attempts, window_seconds)

def check_rate_limit(ip: str, endpoint: str):
    if endpoint not in RATE_LIMITS:
        return
    max_attempts, window = RATE_LIMITS[endpoint]
    now = time.time()
    conn = get_db()
    c = conn.cursor()
    row = c.execute("SELECT attempts, window_start FROM rate_limit WHERE ip=? AND endpoint=?", (ip, endpoint)).fetchone()
    if row:
        attempts, ws = row["attempts"], float(row["window_start"])
        if now - ws < window:
            if attempts >= max_attempts:
                conn.close()
                raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {int(window-(now-ws))}s")
            c.execute("UPDATE rate_limit SET attempts=attempts+1 WHERE ip=? AND endpoint=?", (ip, endpoint))
        else:
            c.execute("UPDATE rate_limit SET attempts=1, window_start=? WHERE ip=? AND endpoint=?", (str(now), ip, endpoint))
    else:
        c.execute("INSERT INTO rate_limit VALUES (?,?,1,?)", (ip, endpoint, str(now)))
    conn.commit()
    conn.close()

# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(title="Auth Service", version="1.0.0", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()

# ── Models ─────────────────────────────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: str
    username: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class BuyAgentRequest(BaseModel):
    agent_id: str
    price_usd: float

class RefreshRequest(BaseModel):
    refresh_token: str

# ── Dependency: get current user from JWT ──────────────────────────────────────
def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    return payload

# ── Password validation ────────────────────────────────────────────────────────
def validate_password(pw: str):
    if len(pw) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not re.search(r"[A-Z]", pw):
        raise HTTPException(status_code=400, detail="Password must contain an uppercase letter")
    if not re.search(r"\d", pw):
        raise HTTPException(status_code=400, detail="Password must contain a digit")

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.post("/auth/signup")
async def signup(req: SignupRequest, request: Request):
    ip = request.client.host
    check_rate_limit(ip, "/auth/signup")

    validate_password(req.password)
    if len(req.username) < 3 or not re.match(r"^[a-zA-Z0-9_]+$", req.username):
        raise HTTPException(status_code=400, detail="Username must be 3+ alphanumeric/underscore chars")
    if "@" not in req.email or "." not in req.email:
        raise HTTPException(status_code=400, detail="Invalid email")

    user_id  = secrets.token_hex(16)
    pwd_hash = hash_password(req.password)
    now      = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (id, email, username, pwd_hash, created_at) VALUES (?,?,?,?,?)",
            (user_id, req.email.lower().strip(), req.username.strip(), pwd_hash, now)
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=409, detail="Email or username already exists")
    finally:
        conn.close()

    access  = create_access_token(user_id, req.email, req.username)
    raw, h  = create_refresh_token(user_id)
    exp     = (datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE_D)).isoformat()
    conn2   = get_db()
    conn2.execute("INSERT INTO refresh_tokens VALUES (?,?,?)", (h, user_id, exp))
    conn2.commit()
    conn2.close()

    return {
        "access_token":  access,
        "refresh_token": raw,
        "token_type":    "bearer",
        "expires_in":    ACCESS_EXPIRE_M * 60,
        "user":          {"id": user_id, "email": req.email, "username": req.username}
    }

@app.post("/auth/login")
async def login(req: LoginRequest, request: Request):
    ip = request.client.host
    check_rate_limit(ip, "/auth/login")

    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM users WHERE email=? AND is_active=1", (req.email.lower().strip(),)
    ).fetchone()
    conn.close()

    # Constant-time check even if user not found (prevent user enumeration)
    dummy_hash = "a" * 65
    stored     = row["pwd_hash"] if row else dummy_hash
    ok         = verify_password(req.password, stored)
    if not row or not ok:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access = create_access_token(row["id"], row["email"], row["username"])
    raw, h = create_refresh_token(row["id"])
    exp    = (datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE_D)).isoformat()
    conn2  = get_db()
    conn2.execute("INSERT OR REPLACE INTO refresh_tokens VALUES (?,?,?)", (h, row["id"], exp))
    conn2.commit()
    conn2.close()

    # Fetch purchased agents for this user
    conn3   = get_db()
    agents  = [r["agent_id"] for r in conn3.execute(
        "SELECT agent_id FROM purchased_agents WHERE user_id=?", (row["id"],)
    ).fetchall()]
    conn3.close()

    return {
        "access_token":      access,
        "refresh_token":     raw,
        "token_type":        "bearer",
        "expires_in":        ACCESS_EXPIRE_M * 60,
        "user":              {"id": row["id"], "email": row["email"], "username": row["username"]},
        "purchased_agents":  agents
    }

@app.post("/auth/refresh")
async def refresh_token_endpoint(req: RefreshRequest):
    h    = hashlib.sha256(req.refresh_token.encode()).hexdigest()
    now  = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM refresh_tokens WHERE token_hash=? AND expires_at > ?", (h, now)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user = conn.execute("SELECT * FROM users WHERE id=? AND is_active=1", (row["user_id"],)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    access = create_access_token(user["id"], user["email"], user["username"])
    return {"access_token": access, "token_type": "bearer", "expires_in": ACCESS_EXPIRE_M * 60}

@app.post("/auth/logout")
async def logout(req: RefreshRequest):
    h    = hashlib.sha256(req.refresh_token.encode()).hexdigest()
    conn = get_db()
    conn.execute("DELETE FROM refresh_tokens WHERE token_hash=?", (h,))
    conn.commit()
    conn.close()
    return {"message": "Logged out"}

@app.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    conn   = get_db()
    agents = [r["agent_id"] for r in conn.execute(
        "SELECT agent_id FROM purchased_agents WHERE user_id=?", (user["sub"],)
    ).fetchall()]
    conn.close()
    return {"user": {"id": user["sub"], "email": user["email"], "username": user["username"]}, "purchased_agents": agents}

@app.post("/auth/buy")
async def buy_agent(req: BuyAgentRequest, user: dict = Depends(get_current_user)):
    now  = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO purchased_agents VALUES (?,?,?,?)",
            (user["sub"], req.agent_id, now, req.price_usd)
        )
        conn.commit()
    finally:
        conn.close()

    # Return updated purchased list
    conn2  = get_db()
    agents = [r["agent_id"] for r in conn2.execute(
        "SELECT agent_id FROM purchased_agents WHERE user_id=?", (user["sub"],)
    ).fetchall()]
    conn2.close()
    return {"success": True, "agent_id": req.agent_id, "purchased_agents": agents}

# ── Internal validation endpoint (called by other agents) ─────────────────────
@app.get("/auth/internal/validate")
async def internal_validate(
    authorization: Optional[str] = Header(None),
    x_internal_secret: Optional[str] = Header(None)
):
    """Called by agent services to verify a user JWT. Never exposed to browser."""
    if x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = get_current_user(authorization)
    return {"valid": True, "user_id": user["sub"], "email": user["email"]}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8004)  # Bind to localhost only — not public
