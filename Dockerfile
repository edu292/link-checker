FROM docker.io/library/python:3.14.2-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:alpine3.23 /usr/local/bin/uv /bin/

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python \
    UV_LINK_MODE=copy \
    PTTHONUNBUFERED=1

RUN uv pip install playwright \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /root/.cache/ms-playwright/firefox* \
    && rm -rf /root/.cache/ms-playwright/webkit*

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --no-dev --format requirements.txt | uv pip install -r -

COPY src/ .

CMD ["python", "main.py"]
