#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/backup_database.sh BACKUP_FILE" >&2
  exit 2
fi

backup_file=$1
backup_directory=$(dirname "$backup_file")
if [[ ! -d "$backup_directory" ]]; then
  echo "Backup directory does not exist: $backup_directory" >&2
  exit 2
fi
if [[ -e "$backup_file" ]]; then
  echo "Refusing to overwrite existing backup: $backup_file" >&2
  exit 2
fi

umask 077
partial_file="${backup_file}.partial"
if [[ -e "$partial_file" ]]; then
  echo "Refusing to overwrite partial backup: $partial_file" >&2
  exit 2
fi
trap 'rm -f "$partial_file"' EXIT
docker compose exec -T postgres \
  pg_dump --username devdna --dbname devdna --format=custom > "$partial_file"
docker compose exec -T postgres pg_restore --list < "$partial_file" > /dev/null
mv "$partial_file" "$backup_file"
trap - EXIT
echo "Verified backup written to $backup_file"
