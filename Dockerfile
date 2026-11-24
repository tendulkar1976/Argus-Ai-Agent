FROM node:24-bookworm-slim AS ui
WORKDIR /build
ENV NEXT_TELEMETRY_DISABLED=1
COPY studio/package*.json ./
RUN npm ci
COPY studio/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m -u 10001 argus
COPY argus argus
COPY alembic.ini .
COPY migrations migrations
COPY --from=ui /build/out studio/out
RUN mkdir .argus && chown argus:argus .argus
USER argus
EXPOSE 8000
CMD ["sh","-c","python -m argus.cli init && exec uvicorn argus.api:app --host 0.0.0.0 --port 8000 --no-access-log"]
