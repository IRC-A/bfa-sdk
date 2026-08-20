FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY bfa_sdk/ ./bfa_sdk/
COPY bfa_gateway/ ./bfa_gateway/
COPY poc/ ./poc/

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ENV BFA_GATEWAY_HOST=0.0.0.0
ENV BFA_GATEWAY_PORT=8000

CMD ["irc-a-gateway"]
