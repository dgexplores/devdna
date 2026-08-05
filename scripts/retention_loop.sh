#!/bin/sh
set -eu

while true; do
  echo "Running retention batch at $(date -u +%FT%TZ)..."
  python -m devdna.retention
  echo "Sleeping 24h."
  sleep 86400
done
