# One image for all Python services (API, processor, jobs); the command picks the role.
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY contracts ./contracts
COPY sql ./sql
COPY data/reference ./data/reference
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 1000 pomorie
USER pomorie

CMD ["python", "-m", "pomorie.processing.consumer"]
