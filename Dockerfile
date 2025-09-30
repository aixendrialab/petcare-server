# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# ---- deps (cacheable) ----
FROM base AS deps
COPY requirements.txt .
RUN python -m pip install --upgrade pip wheel setuptools \
 && pip install -r requirements.txt

# ---- runtime ----
FROM base AS runtime
COPY --from=deps /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=deps /usr/local/bin /usr/local/bin
# app code
COPY app ./app
# If you need schema/seed endpoints inside the container, uncomment:
# COPY schema.sql seed.sql ./
ENV HOST=0.0.0.0 PORT=8001 APP_IMPORT=app.main:app
EXPOSE 8001
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8001","--proxy-headers","--forwarded-allow-ips","*"]
