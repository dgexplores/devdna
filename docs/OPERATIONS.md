# Operations runbook

## Configuration and authentication

Copy `.env.example` to `.env` for local overrides. Staging and production require `DEVDNA_API_KEYS`. Generate high-entropy secrets with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Configure comma-separated `client=secret` entries and send `Authorization: Bearer client.secret` when creating an analysis. Rotate without downtime by adding the new key, deploying, moving clients, then removing the old key.

## Deployment and migrations

Build and start the stack with:

```bash
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:8000/health/ready
```

The `migrate` service must finish successfully before the API starts. Migrations are additive and versioned. Roll back the application image before attempting a database downgrade; take and verify a backup first.

## Monitoring and error diagnostics

Scrape `/metrics` in Prometheus text format and capture JSON logs from standard output. Every response includes `X-Request-ID`; a safe caller-provided value is preserved, allowing a failed request to be located in logs.

Alert initially on:

- readiness returning `503` for two consecutive checks;
- any sustained API `5xx` rate;
- p95 latency above 500 ms on health/report reads;
- repeated `401` or `429` responses;
- worker failures or a growing Redis queue.

TLS, monitoring-network access to `/metrics`, log retention, and alert delivery belong to the deployment platform.

## Retention

The default policy deletes terminal analyses after 90 days in batches of 500. Queued and running analyses are excluded. Run one bounded batch with:

```bash
docker compose --profile maintenance run --rm retention
```

Schedule that command daily in the deployment scheduler. Adjust `DEVDNA_ANALYSIS_RETENTION_DAYS` and `DEVDNA_RETENTION_BATCH_SIZE` only after reviewing storage and privacy requirements.

## Backup and restore

Start PostgreSQL, then create a private, verified custom-format backup:

```bash
scripts/backup_database.sh /absolute/private/path/devdna.backup
```

Copy backups to encrypted off-host storage and define retention in that storage. Test restoration regularly. Restoring replaces current DevDNA database contents, so the command requires an explicit confirmation flag:

```bash
scripts/restore_database.sh /absolute/private/path/devdna.backup --confirm
```

The restore script verifies the archive, stops API and worker writes, restores the database, reapplies migrations, and restarts both processes. Keep the original backup until report and readiness smoke checks pass.

## Load smoke test

With the stack running, exercise the bounded read path:

```bash
uv run python -m devdna.load_smoke \
  --requests 200 \
  --concurrency 20 \
  --max-error-rate 0 \
  --max-p95-ms 500
```

This is a deployment smoke threshold, not a capacity forecast. Run a longer environment-specific test before changing worker counts or infrastructure size.

## Shutdown and rollback

Stop services without deleting database volumes:

```bash
docker compose down
```

Never add `--volumes` unless permanent local data deletion is intentional. Roll back with the previous application image and retain the database at its current schema unless the migration runbook explicitly proves downgrade safety.
