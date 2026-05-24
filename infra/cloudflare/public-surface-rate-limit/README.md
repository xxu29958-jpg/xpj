# Public Surface Rate Limit Worker

This Worker is the optional Cloudflare edge gate in front of the self-hosted
backend. It protects only the two public unauthenticated surfaces:

- `POST /api/auth/pair`
- `POST /u/{upload_key}` and other methods that hit the upload-link route

The Worker uses Cloudflare's Workers Rate Limiting binding at `30` requests per
minute per `cf-connecting-ip` and route class. Backend quotas remain
authoritative; this edge layer only rejects obvious bursts before they reach
the home server.

Deploy:

```powershell
cd infra/cloudflare/public-surface-rate-limit
wrangler secret put ORIGIN_BASE_URL
wrangler deploy
```

`ORIGIN_BASE_URL` must be the HTTPS origin that currently receives the
Cloudflare Tunnel traffic. Keep `/owner` local-only; do not route Owner Console
through this Worker.
