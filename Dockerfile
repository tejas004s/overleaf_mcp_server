# Official Microsoft Playwright image with Python 3.12 & Chromium + OS dependencies pre-installed
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Install git for optional Overleaf Git Bridge support alongside Playwright Browser mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    OVERLEAF_HEADLESS=true \
    MCP_HOST=0.0.0.0 \
    MCP_TRANSPORT=streamable-http

COPY pyproject.toml requirements.txt README.md ./
COPY src/ ./src/
COPY main.py setup_auth.py export_session.py run_server.sh ./

RUN pip install --no-cache-dir -e . && playwright install chromium

EXPOSE 8000

CMD ["python3", "main.py"]
