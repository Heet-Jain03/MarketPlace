# Agent Marketplace — Secure Deployment Guide

## What's New (Security Upgrade)

- ✅ **JWT Authentication** — Login/Signup with access + refresh tokens
- ✅ **Internal agent tokens hidden** — Never sent to browser; server-to-server only
- ✅ **Rate limiting** — Login (5/5min) and Signup (3/10min) per IP
- ✅ **Password hashing** — PBKDF2-SHA256 with 310,000 iterations
- ✅ **User database** — SQLite (no extra DB server needed)
- ✅ **Buy Agent flow** — Purchase tracking per user
- ✅ **XSS prevention** — All output escaped before DOM insertion
- ✅ **Auth service on localhost only** — Port 8004 never exposed to internet
- ✅ **Token auto-refresh** — Silently refreshes every 50 minutes
- ✅ **Session storage** — Tokens cleared when browser tab closes
- ✅ **Docker image** — Single container runs all 5 services

---

## File Structure

```
agent-marketplace/
├── auth_service.py     ← NEW: JWT auth, signup/login, buy tracking (port 8004)
├── llm_client.py       ← UPDATED: JWT verification shared by all agents
├── research1.py        ← UPDATED: JWT + internal token auth (port 8001)
├── writer2.py          ← UPDATED: JWT + internal token auth (port 8002)
├── analyst3.py         ← UPDATED: JWT + internal token auth (port 8003)
├── orchestrator.py     ← UPDATED: JWT required, internal tokens hidden (port 8000)
├── marketplace.html    ← UPDATED: Login/Signup UI, Buy modal, JWT flow
├── requirements.txt    ← UPDATED: added PyJWT
├── Dockerfile          ← NEW: single image, all 5 services
├── start_all.sh        ← NEW: startup script for Docker
├── .env.example        ← NEW: template for secrets
├── .gitignore          ← NEW: protects .env and DB files
└── README.md
```

---

## Step 1 — Set Up Secrets (Critical)

Generate strong secrets:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"  # run 3 times
```

Copy `.env.example` to `.env` and fill in:
```bash
cp .env.example .env
nano .env  # or vim .env
```

Fill in:
```bash
JWT_SECRET=<64-char hex from above>
INTERNAL_SECRET=<another 64-char hex>
AGENT_TOKEN_RESEARCH=<another random string>
AGENT_TOKEN_WRITER=<another random string>
AGENT_TOKEN_ANALYST=<another random string>
GROQ_API_KEY=gsk_your_key_here  # or OPENROUTER_API_KEY
```

**NEVER commit `.env` to git** — it's in `.gitignore` already.

---

## Step 2 — AWS EC2 Security Group Rules

In your EC2 Security Group, allow **inbound** on:

| Port | Source | Purpose |
|------|--------|---------|
| 22   | Your IP only | SSH |
| 8000 | 0.0.0.0/0 | Orchestrator (public) |
| 8001 | 0.0.0.0/0 | ResearchBot (public) |
| 8002 | 0.0.0.0/0 | WriteBot (public) |
| 8003 | 0.0.0.0/0 | AnalystBot (public) |

**Port 8004 (Auth Service) — DO NOT add to security group.**
It binds to `127.0.0.1` (localhost only) — unreachable from internet by design.

---

## Step 3 — Deploy with Docker (Recommended)

### On your local machine:
```bash
# Build the image
docker build -t agent-marketplace .

# Save and transfer to EC2
docker save agent-marketplace | gzip > marketplace.tar.gz
scp marketplace.tar.gz ec2-user@<EC2-IP>:~/
```

### On EC2:
```bash
# Load the image
docker load < marketplace.tar.gz

# Run with environment variables from .env file
docker run -d \
  --name marketplace \
  --env-file .env \
  -p 8000:8000 \
  -p 8001:8001 \
  -p 8002:8002 \
  -p 8003:8003 \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  agent-marketplace

# Check logs
docker logs -f marketplace
```

---

## Step 4 — Deploy without Docker (Git method)

### On EC2:
```bash
# Clone / pull your repo
git clone https://github.com/your-repo/agent-marketplace.git
cd agent-marketplace

# Install deps
pip3 install -r requirements.txt

# Set env variables (they will NOT be in git)
export JWT_SECRET="your-jwt-secret"
export INTERNAL_SECRET="your-internal-secret"
export AGENT_TOKEN_RESEARCH="your-research-token"
export AGENT_TOKEN_WRITER="your-writer-token"
export AGENT_TOKEN_ANALYST="your-analyst-token"
export GROQ_API_KEY="gsk_..."

# Start all services (4 terminals or use screen/tmux)
# Terminal 1:
uvicorn auth_service:app --host 127.0.0.1 --port 8004

# Terminal 2:
uvicorn research1:app --host 0.0.0.0 --port 8001

# Terminal 3:
uvicorn writer2:app --host 0.0.0.0 --port 8002

# Terminal 4:
uvicorn analyst3:app --host 0.0.0.0 --port 8003

# Terminal 5:
uvicorn orchestrator:app --host 0.0.0.0 --port 8000
```

### Using screen to keep services alive:
```bash
screen -S auth     && uvicorn auth_service:app --host 127.0.0.1 --port 8004 && screen -d
screen -S research && uvicorn research1:app    --host 0.0.0.0   --port 8001 && screen -d
screen -S writer   && uvicorn writer2:app      --host 0.0.0.0   --port 8002 && screen -d
screen -S analyst  && uvicorn analyst3:app     --host 0.0.0.0   --port 8003 && screen -d
screen -S orch     && uvicorn orchestrator:app --host 0.0.0.0   --port 8000 && screen -d
```

---

## Step 5 — Open the UI

Open `marketplace.html` in your browser with your EC2 IP configured:

The HTML auto-detects the hostname: if you open it from EC2 IP, it connects to EC2 automatically.

Or serve it:
```bash
# Serve the HTML on EC2
python3 -m http.server 8080  # then open http://<EC2-IP>:8080/marketplace.html
# Add port 8080 to security group for this
```

---

## Step 6 — Using the Marketplace

1. **Sign Up** — Create account with email, username, password
2. **Sign In** — Login returns JWT access + refresh tokens
3. **Save LLM key** — Enter Groq or OpenRouter key in the yellow bar
4. **Buy agents** — Click "Buy Agent" → confirm purchase → unlocked
5. **Run agents** — Fill form and click Run
6. **Run pipelines** — Multi-agent A2A chains

---

## Security Architecture

```
Browser
  │
  │  1. POST /auth/login → gets JWT access token
  │  2. Bearer <JWT> → sent with every agent call
  │  3. Agent tokens NEVER sent to browser
  │
  ▼
[EC2 Public Ports: 8000-8003]
  │
  │  JWT verified by each agent/orchestrator locally
  │
  ▼
Orchestrator (8000) ─── JWT verified ──► calls agents with internal X-Agent-Token
  │                                         (token is in env, never in browser)
  ├─► ResearchBot (8001) ← internal token only
  ├─► WriteBot    (8002) ← internal token only
  └─► AnalystBot  (8003) ← internal token only

Auth Service (8004) ← localhost only, NOT reachable from internet
  - Stores users in SQLite (users.db)
  - Issues JWT access tokens (60 min)
  - Issues refresh tokens (7 days)
  - Tracks purchased agents per user
```

## Security Features Against Attacks

| Attack | Protection |
|--------|-----------|
| Brute force login | Rate limit: 5 attempts/5min per IP |
| Password leak | PBKDF2-SHA256, 310,000 iterations, salted |
| Token theft | Short-lived access tokens (60 min) |
| XSS | All output HTML-escaped before DOM insertion |
| Token enumeration | Constant-time password comparison |
| Internal token exposure | Tokens in env vars, never in browser or HTML |
| Agent poisoning/shadowing | JWT required on every /a2a/execute call |
| Tool injection | JSON schema validation on all inputs via Pydantic |
| Session persistence | sessionStorage (cleared on tab close), not localStorage |

---

## Updating on EC2 via Git

```bash
# Push from your machine
git add -A
git commit -m "your message"
git push origin main

# On EC2
cd agent-marketplace
git pull origin main

# Restart (Docker)
docker restart marketplace

# OR restart (no Docker)
# kill the uvicorn processes and re-run them
```

---

## Troubleshooting

**"JWT_SECRET not set"** → Set the `JWT_SECRET` environment variable before starting

**"Token expired"** → User needs to log in again (or tokens auto-refresh every 50min)

**Port 8004 refusing connection** → Auth service binds to 127.0.0.1 only — this is correct

**CORS error** → All agents have CORS enabled for `*`; if persists, check EC2 security group

**"Invalid agent token"** → Make sure `AGENT_TOKEN_RESEARCH/WRITER/ANALYST` env vars match in orchestrator and agents

**users.db not found** → First run creates it automatically in the working directory
