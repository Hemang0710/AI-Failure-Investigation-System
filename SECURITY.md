# Security Policy

## Reporting a Vulnerability

Please report security issues **privately** — do not open a public GitHub issue.

- Email **hemangpatel0710@gmail.com** with a description, reproduction steps, and impact.
- Or use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  ("Report a vulnerability" on the Security tab).

You can expect an acknowledgement within **5 business days**. Please allow a
reasonable window to release a fix before any public disclosure.

## Supported Versions

This project is pre-1.0; security fixes are applied to the `main` branch.

## Authentication

- API keys are random, per-user, and stored **only as SHA-256 hashes** — the
  plaintext key is never written to the database.
- All `/api/v1` routes require a valid `Authorization: Bearer <key>` and are
  rate limited per key (per client IP for unauthenticated requests).
- Provision keys via `BOOTSTRAP_API_KEY`; if unset, the backend generates one
  and prints it **once** at startup.

## Data Handling

This system ingests raw LLM prompts and responses, which frequently contain
personal or sensitive data. Two controls limit exposure:

### PII redaction (on by default)

At ingestion — before anything is persisted — prompts, responses, and retrieved
documents are scanned and matching values are replaced with placeholders such as
`[REDACTED_EMAIL]`. Configure via `PII_REDACTION_ENABLED` and
`PII_REDACTION_TYPES`.

Detectors: `email`, `credit_card` (Luhn-validated), `ssn` (US), `phone`, `ip`,
`api_key` (common provider/AWS/GitHub/JWT shapes).

**Scope and limitations.** Redaction is regex-based and best-effort. It targets
structured, high-signal identifiers and will **not** catch free-form names,
physical addresses, or context-dependent PII. It does **not** scan the
caller-controlled `event_metadata` or `tags` fields — do not put secrets there.
For stronger guarantees, redact at the source before sending events, or run a
dedicated PII engine upstream. Redaction is destructive: the original text is
never stored.

### Retention (off by default)

Set `DATA_RETENTION_DAYS` to automatically delete events (and their feedback)
older than N days. A background sweep runs every `RETENTION_SWEEP_INTERVAL_HOURS`.
The default of `0` keeps data indefinitely so that upgrading never silently
deletes existing records.

## Deployment Notes

- Never expose the database port publicly; the provided compose file binds it to
  `127.0.0.1` only.
- Set strong, unique values for `POSTGRES_PASSWORD` and `API_KEY`.
- Terminate TLS at a reverse proxy in production and have it enforce a request
  body size limit (the app checks `Content-Length`, but a proxy should bound
  streamed/chunked bodies too).
- Scope `CORS_ORIGINS` to the hosts that actually serve the dashboard/UI.
