# Source discovery only: Semgrep runs against a read-only source mount.
FROM python:3.11-slim-bookworm

ARG SEMGREP_VERSION=1.161.0
RUN pip install --no-cache-dir "semgrep==${SEMGREP_VERSION}" && \
    groupadd -g 1000 sandbox && useradd -u 1000 -g sandbox -m sandbox
ENV HOME=/home/sandbox PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER sandbox
WORKDIR /workspace
CMD ["semgrep", "--version"]
