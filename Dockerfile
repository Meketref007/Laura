FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder
COPY . .
RUN pip install --no-cache-dir -e ".[all]"

FROM base AS runtime
COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app

EXPOSE 8888

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8888/ || exit 1

ENTRYPOINT ["python", "-m", "shopee_agent.cli"]
CMD ["api-serve"]
