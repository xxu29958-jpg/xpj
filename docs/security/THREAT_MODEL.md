# Threat Model

Scope: family self-hosted 小票夹 with Android, `/web`, local-only `/owner`,
public UploadLink, and pairing through Cloudflare Tunnel.

Assets: receipt photos, parsed expense rows, ledger membership, app tokens,
upload keys, pairing codes, backups, AI advisor audit rows, and local `.env`
runtime settings.

- `/u/{upload_key}` is unauthenticated by bearer token because the upload key is
  the credential. Controls: high-entropy key, per-link daily byte quota,
  per-remote throttle, upload size/type limits, optional Cloudflare Worker
  30 req/min/IP edge limit.
- `/api/auth/pair` accepts pairing codes. Controls: short-lived one-shot codes,
  DB-backed failed-attempt throttle, app-token expiry metadata, optional
  Cloudflare Worker 30 req/min/IP edge limit.
- `/web` is browser-session gated. Controls: cookie/session auth, CSRF tests,
  ledger scoping, and no Owner Console exposure.
- `/api/admin/*` is local-only by default. If `ALLOW_PUBLIC_ADMIN_API=true`,
  startup requires Cloudflare Access configuration and requests require Access
  JWT validation.
- `/owner` manages devices, upload links, settings, backups, and AI advisor
  confirmation. Controls: loopback boundary, CSRF, no raw token/key listing,
  and explicit runtime-edit whitelist.
- Ledger IDs in request bodies are not trusted as authority; bearer session
  context owns tenant scope.
- Viewer role must not mutate expenses, rules, budgets, links, or members.
- Missing vs forbidden cross-ledger objects should not reveal existence.
- AI advisor payloads cross the privacy boundary only after owner confirmation;
  outbound payloads are anonymized and audit logs store hashes, not raw payloads.
- Alembic owns new schema changes after the v1.1 baseline.
- `release_audit` checks route coverage, auth-401 markers, CSRF dual mode, CI
  gaps, service graph, and codebase checks.
- `pip-audit` and OWASP dependency-check gate known vulnerable dependencies.
