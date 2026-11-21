# 1) Сборка Mini App
FROM node:22-alpine AS web
WORKDIR /web
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci
COPY miniapp/ ./
RUN npm run build

# 2) Python: API + бот
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MINIAPP_DIST=/app/miniapp_dist
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import jieba; jieba.initialize()"
COPY backend/ ./
COPY --from=web /web/dist /app/miniapp_dist
RUN useradd -m app && mkdir -p /data/audio && chown -R app /data /app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
