FROM python:3.11-slim

WORKDIR /app

# Install git (required for Overleaf Git Bridge synchronization)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

ENV OVERLEAF_WORKSPACE_DIR=/data/overleaf_workspace \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000

CMD ["overleaf-mcp"]
