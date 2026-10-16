# Share the universal uv.lock with native macOS/Linux development.
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv
FROM python:3.12-slim-bookworm AS builder
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_HTTP_TIMEOUT=120
COPY --from=uv /uv /bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN uv sync --locked --no-dev --no-editable \
    && .venv/bin/python -c 'import arq, ijson, psycopg; from tree_sitter_language_pack import get_language; get_language("java")'

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 curl ripgrep git openssh-client ca-certificates \
        libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
        libcairo2 libgdk-pixbuf-2.0-0 libglib2.0-0 \
        shared-mime-info fontconfig fonts-noto-cjk \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY . .
RUN mkdir -p /app/uploads/zip_files \
    && sed -i 's/\r$//' /app/docker-entrypoint.sh \
    && chmod +x /app/docker-entrypoint.sh
EXPOSE 8000
CMD ["/app/docker-entrypoint.sh"]
