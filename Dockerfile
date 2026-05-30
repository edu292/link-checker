FROM mcr.microsoft.com/playwright/python:v1.60.0-noble-amd64
COPY --from=ghcr.io/astral-sh/uv:alpine3.23 /usr/local/bin/uv /usr/local/bin/uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_PYTHON=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip compile pyproject.toml -o - | uv pip install -r -

COPY main.py ./

CMD ["python", "main.py"]
