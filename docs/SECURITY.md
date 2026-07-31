# Security baseline

## Release 1 trust boundaries

DevDNA reads public GitHub data only. Recruiter batches accept bounded CSV or DOCX lists of public
GitHub usernames; uploaded bytes are parsed in memory and are not persisted. Batch ownership and
retention apply to the filename, candidate mapping, and resulting public evidence. DevDNA does not
accept CV content, OAuth tokens, or private-repository data.

`POST /v1/analyses` requires a bearer API key whenever `DEVDNA_API_KEYS` is configured; staging and production refuse to start without that configuration. Read-only reports remain public because they contain public GitHub evidence. Each key uses `client=secret` configuration and `Authorization: Bearer client.secret` at the API boundary. Secrets must be at least 24 characters, live only in the deployment secret store, and be rotated by adding a replacement before removing the old entry.

Analysis history is owner-scoped even though the underlying GitHub evidence is public. The web app
exchanges a valid access key for a signed, time-limited, HttpOnly, SameSite cookie. Production
requires a separate `DEVDNA_WEB_SESSION_SECRET`; it must not reuse an API key or GitHub token.
The cookie is marked Secure outside development and test environments. API history authenticates
every request and joins through the ownership table rather than trusting a caller-supplied owner.

Analysis creation is throttled per authenticated client. Missing or invalid credentials, and development without configured keys, are throttled by the direct peer address. DevDNA deliberately ignores forwarded client headers until the deployment has an explicit trusted-proxy allowlist.

## Application controls

- Mutation requests require `Content-Length` and are rejected above the configured body limit.
- Redis rate-limit failure closes analysis creation instead of bypassing protection.
- Request IDs are validated before entering logs and returned in every response.
- Security headers prevent MIME sniffing and framing; report pages use a restrictive content security policy.
- Logs contain operational context but never authorization headers, API secrets, or GitHub tokens.
- Completed, partial, and failed analyses expire after 90 days by default. Active jobs are never deleted by retention.
- Recruiter uploads are capped by bytes, candidate count, and an independent per-owner request
  limit. Batch metadata expires under the same retention policy.

## Operational controls

The deployment must terminate TLS, restrict `/metrics` to the monitoring network, capture structured standard-output logs, encrypt backups, and alert on readiness failures, `5xx` responses, elevated latency, and repeated `401`/`429` responses. See [the operations runbook](OPERATIONS.md).

Recruitment features must preserve human review, explain evidence, exclude protected-trait inference, and never autonomously accept or reject a candidate.
