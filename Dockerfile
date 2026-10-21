FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
RUN python -c "import subprocess,tomllib; subprocess.check_call(['pip','install',*tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']])" \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 mcp \
    && mkdir /workspace /data && chown mcp:mcp /workspace /data \
    && chmod -R a+rX /ms-playwright
COPY src/ ./src/
COPY README.md LICENSE ./
COPY scripts/verify_install.py scripts/configure_client.py /app/
RUN pip install --no-deps .
USER mcp
CMD ["same-energy-mcp"]

FROM runtime AS test
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/ /scripts/
COPY tests/ /tests/
USER mcp
RUN python -m unittest discover -s /tests -v

FROM runtime AS production
