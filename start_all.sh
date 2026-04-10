#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# start_all.sh — Starts all 5 services inside the Docker container
# Auth service binds to 127.0.0.1 (localhost only — not reachable from internet)
# ──────────────────────────────────────────────────────────────────────────────

set -e

echo "=== Agent Marketplace Starting ==="
echo "Checking required environment variables..."

if [ -z "$JWT_SECRET" ]; then
  echo "ERROR: JWT_SECRET is not set. Refusing to start."
  exit 1
fi
if [ -z "$INTERNAL_SECRET" ]; then
  echo "ERROR: INTERNAL_SECRET is not set. Refusing to start."
  exit 1
fi

echo "Environment OK"

# Auth service — binds to localhost ONLY (127.0.0.1)
# Not reachable from outside the container/EC2 instance
echo "Starting Auth Service on 127.0.0.1:8004..."
uvicorn auth_service:app --host 127.0.0.1 --port 8004 --log-level warning &
AUTH_PID=$!

sleep 1

# Research agent
echo "Starting ResearchBot on 0.0.0.0:8001..."
uvicorn research1:app --host 0.0.0.0 --port 8001 --log-level warning &
R_PID=$!

# Writer agent
echo "Starting WriteBot on 0.0.0.0:8002..."
uvicorn writer2:app --host 0.0.0.0 --port 8002 --log-level warning &
W_PID=$!

# Analyst agent
echo "Starting AnalystBot on 0.0.0.0:8003..."
uvicorn analyst3:app --host 0.0.0.0 --port 8003 --log-level warning &
A_PID=$!

# Orchestrator
echo "Starting Orchestrator on 0.0.0.0:8000..."
uvicorn orchestrator:app --host 0.0.0.0 --port 8000 --log-level warning &
O_PID=$!

echo ""
echo "=== All services started ==="
echo "  Auth Service  → http://127.0.0.1:8004  (internal only)"
echo "  Orchestrator  → http://0.0.0.0:8000"
echo "  ResearchBot   → http://0.0.0.0:8001"
echo "  WriteBot      → http://0.0.0.0:8002"
echo "  AnalystBot    → http://0.0.0.0:8003"
echo ""

# Wait for any service to exit (if one crashes, container restarts)
wait -n $AUTH_PID $R_PID $W_PID $A_PID $O_PID
echo "A service exited — container will restart"
