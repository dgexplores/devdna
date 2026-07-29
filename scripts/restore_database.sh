#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || $2 != "--confirm" ]]; then
  echo "Usage: scripts/restore_database.sh BACKUP_FILE --confirm" >&2
  exit 2
fi

backup_file=$1
if [[ ! -s "$backup_file" ]]; then
  echo "Backup file is missing or empty: $backup_file" >&2
  exit 2
fi

docker compose exec -T postgres pg_restore --list < "$backup_file" > /dev/null
docker compose stop api worker
docker compose exec -T postgres \
  pg_restore \
  --username devdna \
  --dbname devdna \
  --clean \
  --if-exists \
  --no-owner \
  --exit-on-error < "$backup_file"
docker compose run --rm migrate
docker compose start api worker
echo "Database restored, migrated, and services restarted"
