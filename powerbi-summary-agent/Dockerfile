FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --requirement requirements.txt


FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_CONFIG_PATH=/app/config/config.example.json

RUN groupadd --system agent \
    && useradd --system --gid agent --create-home --home-dir /home/agent agent

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=agent:agent . .

# The job writes transient run artifacts here before publishing the app-facing
# JSON and memory to Blob Storage. The image never runs as root.
RUN mkdir -p /app/outputs && chown agent:agent /app/outputs

USER agent

CMD ["python", "-m", "src.container_entrypoint"]
