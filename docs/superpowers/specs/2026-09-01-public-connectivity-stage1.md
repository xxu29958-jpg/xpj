# Ticketbox Public Connectivity Backstage Stage 1 Specification

## Authority and subject

- Gmail message id: `1a05a22ed7a61a46`
- Gmail subject: `Ticketbox 公网连接 Backstage / cloudflared 受管接入｜GPT 主提示词 + 完整施工合同｜2026-09-01`
- Product architecture: `Ticketbox_Product_System_Architecture_Current_2026-08-26.pdf`, SHA-256 `1bb42aa2acab90c1237e41f9726eb63f23f524bfc6f23ffeaeac48cb73249327`
- Windows lifecycle architecture: `Ticketbox_Windows_Data_Lifecycle_Architecture_Current_2026-08-26.pdf`, SHA-256 `1e72c3235e3d8d82fc848d5af353e39863752a16545deb61b00fadce59f5dc3a`
- Implementation subject: Desktop Manager Stage 1 read-only Public Connectivity Backstage.

This document is a repository-local execution extract of the Gmail contract. It does not replace the Gmail message or either architecture PDF.

## Stage boundary

Stage 1 is open and must build only:

- a typed public-connectivity read model;
- exact, bounded, read-only Windows SCM and cloudflared diagnostic probes;
- the existing Ticketbox origin-health projection;
- bounded public health, authenticated-product, and public-boundary probes;
- an asynchronous cached provider with staleness and generation ordering;
- a stable AppController JSON projection;
- the Desktop Manager `公网连接` UI and read-only actions;
- a strictly allowlisted diagnostic projection;
- focused unit, integration, UI, privacy, and real-Windows read-only evidence.

Stage 2 remains closed. Stage 1 must not:

- install, download, update, execute, start, stop, restart, repair, or register cloudflared;
- obtain or rotate a tunnel token;
- call Cloudflare account APIs or write DNS/tunnel configuration;
- write `config.yml`, service configuration, Scheduled Tasks, Machine Secrets, installer metadata, Release Manifests, or lifecycle receipts;
- add UAC, helper, installer, repair, restore, upgrade, uninstall, or privileged-mutation behavior;
- publish a mutation button, a disabled mutation placeholder, or an unsupported action in the status contract.

## Responsibility topology

- Desktop Manager owns display, refresh initiation, full public-check initiation, and sanitized diagnostic export.
- PublicConnectivityProvider owns scheduling, cache, freshness, race ordering, and composition of read-only evidence.
- cloudflared adapters own transport and source parsing only; they do not decide product policy and never read a Desktop product session.
- AppController owns the stable Manager API projection and readonly action entry points.
- Lifecycle remains the only future owner of privileged host mutations.
- Cloudflare remains the remote tunnel configuration owner.
- Backend remains the product, session, and business-data truth owner.

## State model

The model carries these independent axes:

- ownership: `unconfigured`, `external_unmanaged`, `managed`, `conflict`, `unknown`
- service: `unknown`, `missing`, `stopped`, `start_pending`, `running`, `stop_pending`, `failed`, `identity_mismatch`
- connector: `unknown`, `connecting`, `healthy`, `degraded`, `down`, `tunnel_mismatch`
- origin: `unknown`, `healthy`, `unreachable`, `identity_mismatch`
- public: `unconfigured`, `unknown`, `reachable_unverified`, `authenticated_reachable`, `unreachable`, `wrong_product`
- boundary: `unknown`, `safe`, `violation`
- freshness: `fresh`, `stale`
- managed action: `unavailable`, `available`, `awaiting_uac`, `running`, `succeeded`, `cancelled`, `failed`, `unknown_outcome`, `manual_intervention`

The overall result is derived in this order:

1. `unsafe` for a public-boundary violation or a protected-identity ownership conflict.
2. `unknown` when the evidence required for a current result is stale.
3. `unknown` for unconfigured, external-unmanaged, or insufficient ownership evidence.
4. `offline` for a managed service that is missing, stopped, or failed.
5. `connector_unavailable` for a down connector or tunnel mismatch.
6. `origin_unavailable` for an unreachable or identity-mismatched Ticketbox origin.
7. `public_unavailable` for an unreachable or wrong-product public endpoint.
8. `degraded` for pending, connecting, partially connected, reachable-unverified, or otherwise incomplete current evidence.
9. `healthy` only when managed ownership, running service, healthy connector, healthy exact origin, authenticated public reachability, safe public boundary, and fresh evidence all hold.

Stale evidence must never render `healthy`.

## Ownership and service evidence

Managed ownership requires a protected connector expectation that binds the installation and release generation to:

- the exact Windows service name;
- the exact binary and exact parsed argv contract;
- the exact SCM account, start mode, and failure-action contract;
- the exact loopback metrics endpoint;
- the expected tunnel and connector identities;
- the Ticketbox origin and public origin.

Stage 1 has no protected connector expectation in the installed release contract. Therefore a running external process, PATH hit, similarly named service, Scheduled Task, or an otherwise healthy `/ready` endpoint can be reported only as `external_unmanaged` or `conflict`; it can never become `managed`.

SCM observation must use native exact-name queries and Windows command-line parsing. It must not use wildcard process discovery, localized `sc.exe` text, copied argv strings, or process presence as service identity.

## Connector evidence

- The transport accepts only fixed `http://127.0.0.1:<port>` endpoints.
- It disables environment proxies and redirects and enforces short timeouts and response-size ceilings.
- External discovery is limited to cloudflared's official fixed default loopback ports `20241` through `20245`.
- `/ready` must be exact JSON containing a canonical UUID `connectorId`, an integer `readyConnections`, and a `status` equal to the HTTP status.
- `/diag/tunnel` must contain canonical UUID `tunnelID` and `connectorID` values and a bounded connections list.
- The adapter exports only safe booleans, version text, and counts. It never exports either UUID, raw connection records, flags, paths, argv, logs, configuration, or token material.
- A protected expectation, when one exists in a later contract, is compared in memory; it is not persisted by this read model.

Cloudflare Edge readiness proves only an active connector-to-Edge path. It does not prove Ticketbox origin health or public product reachability.

## Origin and public evidence

- Origin state reuses the existing exact Ticketbox installation-health attestation and its runtime projection.
- A public origin must be a normalized HTTPS origin with no userinfo, path, query, or fragment.
- Public HTTP disables environment proxies and redirects and uses an eight-second deadline, bounded response bytes, and at most sixteen fixed GET requests.
- Anonymous `/api/health` returning the exact public-safe contract proves only `reachable_unverified`.
- A full check may load the existing Desktop app session only in the coordinator. The bearer is used only in the Authorization header for the public `/api/auth/check` request.
- `authenticated_reachable` requires the Ticketbox auth-check schema, `scope=app`, and equality with the non-secret account, ledger, device, and role metadata stored with the local Desktop session.
- The bearer must never enter a URL, browser, log, exception, status projection, diagnostic bundle, file, environment variable, or subprocess argv.
- An auth rejection after a valid anonymous health response remains `reachable_unverified`; a successful response with the wrong schema or mismatched local session metadata is `wrong_product`.

## Boundary evidence

A full public check uses only safe GET requests and requires:

- `/api/health` to expose only the public-safe health contract;
- anonymous `/api/auth/check` to be denied;
- the loopback installation-health endpoint to be denied;
- Owner Console, Desktop bridge, private status, admin, maintenance, and bootstrap-style paths to be denied or absent;
- a synthetic UploadLink-shaped path to be denied or method-rejected without using a real capability;
- a synthetic upload/static path to be absent;
- redirects or ambiguous responses to remain `unknown`, not be treated as safe.

Any successful response on a forbidden path is a `violation`. Network/timeout ambiguity is `unknown`.

## Stable projection and UI

The AppController projection is `public_connectivity`, schema `ticketbox-public-connectivity-v1`. It replaces the `tunnel: null` placeholder and the duplicate public-endpoint consumer. It includes only:

- overall state, stable code, Chinese summary, and next step;
- the independent state axes and freshness;
- observation timestamps and in-progress state;
- cloudflared version, connection count, and safe identity-match booleans;
- the exact supported read-only actions: `refresh`, `full_check`, `export_diagnostics`.

The UI title is `公网连接`; its subtitle is `由 Cloudflare Tunnel 提供`. The UI renders server-derived policy and does not recompute overall state. It shows Backend, service, Edge, origin, public endpoint, boundary, recent observation, version, and ownership. Its only controls are refresh, full public check, and export diagnostics.

## Freshness and concurrency

- Local read-only refresh cadence: 10 seconds.
- Maximum age for a current complete result: 60 seconds.
- Status reads are cache-only and must not block on SCM, local HTTP, public HTTP, WinCred, or DNS.
- Full checks run outside the control-server request thread.
- Every request receives a monotonically increasing generation. A completed older generation must not overwrite a newer requested generation.
- Manager shutdown cancels queued work and does not wait indefinitely for network I/O.

## Diagnostic allowlist

The diagnostic bundle may include only overall/axis states, freshness, timestamps, version, safe identity-match booleans, connection count, stable code, and managed action state.

It must exclude public origin, tunnel/connector UUIDs, bearer/token/capability values, account or device identifiers, auth headers, full service names when not fixed by contract, paths, ImagePath, argv, SCM raw configuration, logs, certificates, cloudflared configuration, and Ticketbox data.

## Required evidence

Focused automated evidence must cover:

- overall-state matrix and stale healthy demotion;
- external observation never becoming managed;
- exact SCM ImagePath/argv mismatch;
- tunnel/connector mismatch;
- origin/public priority and authenticated versus unverified reachability;
- no-session behavior;
- boundary violation priority;
- absence of unsupported actions;
- diagnostic secret/path/identifier non-leakage;
- no-proxy, no-redirect, loopback/HTTPS validation, oversized body, malformed JSON/schema, and timeout behavior;
- cache-only status behavior and generation race ordering;
- AppController, control-route, UI contract, and Manager startup/shutdown composition.

The real Windows read-only lane must record exact-service absence/presence, external cloudflared observation, real diagnostic endpoint behavior when present, Ticketbox origin state, configured public endpoint state when available, stop/recover observations only when an already-owned safe test fixture exists, and Manager restart without stale healthy carryover. No real-Windows check may mutate cloudflared or lifecycle state.

`PUBLIC_CONNECTIVITY_BACKSTAGE = CLOSED` may be declared only when every Stage 1 gate is satisfied. Otherwise the result names the exact unmet gate and Stage 1 remains open. Stage 2 remains `HOLD` in either case.
