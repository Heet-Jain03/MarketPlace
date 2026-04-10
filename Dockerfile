# ──────────────────────────────────────────────────────────────────────────────
# Dockerfile — Single image running all 5 services on one EC2
# Ports: 8000 (orchestrator), 8001-8003 (agents), 8004 (auth — localhost only)
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Security: run as non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY auth_service.py .
COPY llm_client.py   .
COPY research1.py    .
COPY writer2.py      .
COPY analyst3.py     .
COPY orchestrator.py .
COPY marketplace.html .
COPY start_all.sh    .

# Make startup script executable
RUN chmod +x start_all.sh

# Data directory for SQLite DB (mount a volume here for persistence)
RUN mkdir -p /app/data && chown appuser:appuser /app/data

USER appuser

# Expose public-facing ports only
# 8004 (auth) is internal — NOT exposed to internet via security group
EXPOSE 8000 8001 8002 8003

CMD ["./start_all.sh"]
