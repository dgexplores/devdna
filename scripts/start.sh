#!/bin/sh
set -eu

echo "Applying database migrations..."
alembic upgrade head

echo "Starting API..."
exec uvicorn devdna.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --no-access-log
