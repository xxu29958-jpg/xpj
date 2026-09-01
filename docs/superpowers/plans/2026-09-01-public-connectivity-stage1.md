# Public Connectivity Backstage Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Desktop Manager's read-only Public Connectivity Backstage without introducing any cloudflared, Cloudflare-account, lifecycle, installer, or privileged mutation.

**Architecture:** A pure typed model derives policy from independent evidence axes. Narrow SCM/cloudflared and public-endpoint adapters perform bounded reads, while an asynchronous generation-latched provider owns scheduling, cache, and staleness; AppController, UI, and diagnostics consume only a sanitized stable projection.

**Tech Stack:** Python 3.11, `dataclasses`, `enum.StrEnum`, `ctypes` Win32 SCM APIs, `urllib.request`, `concurrent.futures`, stdlib HTTP control server, HTML/CSS/JavaScript, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-01-public-connectivity-stage1.md`

## Global Constraints

- Exact baseline: commit `9f5b6033ec8be56afa094631371257f2a5bfbfd9`, tree `f95c2ac6efa031f4e65f38da60700eda69486a89`.
- Work only in the isolated branch `codex/public-connectivity-read-model-20260901` and preserve the user's root worktree.
- Stage 1 is read-only. Do not install, download, update, execute, start, stop, restart, repair, register, or configure cloudflared.
- Do not call Cloudflare account APIs, mutate DNS, write tunnel configuration, add UAC/helper behavior, or change installer/lifecycle/release contracts.
- Status reads are cache-only; all SCM, WinCred, DNS, and HTTP work runs off the control-server thread.
- All HTTP transports disable proxies and redirects and enforce exact origins, bounded time, bounded request count, and bounded response bytes.
- A token is accepted only from WinCred by the upper coordinator and appears only in an Authorization header; it never enters a projection, log, exception, URL, file, argv, environment variable, browser, or diagnostic bundle.
- No protected connector binding exists in the current installed contract, so production observation cannot report `managed` or `healthy` in this slice.
- The only public-connectivity UI actions are `refresh`, `full_check`, and `export_diagnostics`.
- Stage 2 remains `HOLD` even if Stage 1 closes.

---

## File structure

- Create `desktop/backend_manager/public_connectivity.py`: pure states, priority derivation, freshness, safe projection, and UI-ready detail rows.
- Create `desktop/backend_manager/cloudflared_contract.py`: privacy-safe adapter contracts.
- Create `desktop/backend_manager/windows_cloudflared_service.py`: native exact-name SCM observation and Windows argv parsing.
- Create `desktop/backend_manager/cloudflared_probe.py`: fixed loopback `/ready` and `/diag/tunnel` transports, protected-expectation comparison, and safe adapter result.
- Create `desktop/backend_manager/public_endpoint_probe.py`: normalized HTTPS transport, anonymous health, authenticated product check, and safe public-boundary matrix.
- Create `desktop/backend_manager/public_connectivity_provider.py`: runtime context loading, async refresh/full-check scheduling, generation commit rule, cache, and monitor loop.
- Modify `desktop/backend_manager/app_controller.py`: inject the provider, expose its stable projection, retire the placeholder consumers, and add two read-only action methods.
- Modify `desktop/backend_manager/control_server.py`: register only the two new CSRF-protected readonly trigger actions in addition to the existing diagnostic export.
- Modify `desktop/backend_manager/manager_startup.py`: construct, start, stop, and join the public-connectivity provider independently of the backend runtime monitor.
- Modify `desktop/backend_manager/diagnostic_bundle.py`: recursively sanitize the one nested public-connectivity projection with a closed allowlist.
- Modify `desktop/backend_manager/ui.html`: add the `公网连接` card, render server-derived details, and wire the three allowed controls.
- Create four focused module test files and modify the existing integration/UI/diagnostic/startup tests listed below.

### Task 1: Pure typed status model

**Files:**
- Create: `desktop/backend_manager/public_connectivity.py`
- Create: `desktop/tests/test_public_connectivity.py`

**Interfaces:**
- Consumes: UTC `datetime` values supplied by the provider.
- Produces: `PublicConnectivityStatus.current(*, evidence_age, max_age) -> PublicConnectivityStatus`, `PublicConnectivityStatus.to_projection() -> dict[str, object]`, all state `StrEnum` classes, and `unknown_public_connectivity_status()`.

- [x] **Step 1: Write the failing state-matrix tests**

Define a `_status(**changes)` fixture over a fully verified managed status and assert the priority contract, including these exact cases:

```python
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"boundary": BoundaryState.VIOLATION}, OverallState.UNSAFE),
        ({"service": ServiceState.STOPPED}, OverallState.OFFLINE),
        ({"connector": ConnectorState.DOWN}, OverallState.CONNECTOR_UNAVAILABLE),
        ({"origin": OriginState.UNREACHABLE}, OverallState.ORIGIN_UNAVAILABLE),
        ({"public": PublicState.WRONG_PRODUCT}, OverallState.PUBLIC_UNAVAILABLE),
        ({"public": PublicState.REACHABLE_UNVERIFIED}, OverallState.DEGRADED),
        ({}, OverallState.HEALTHY),
    ],
)
def test_overall_priority(changes, expected):
    assert replace(_status(), **changes).overall is expected
```

Also assert that stale healthy becomes `unknown`, external/unconfigured ownership cannot be healthy, unsafe wins over staleness, and the projection contains exactly the three read-only actions and no tunnel/connector ID or URL keys.

- [x] **Step 2: Run the focused test and capture the expected RED**

Run from `desktop`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_public_connectivity.py
```

Expected: collection fails because `backend_manager.public_connectivity` does not exist.

- [x] **Step 3: Implement the minimal pure model**

Create `StrEnum` classes for every axis and an immutable dataclass with no transport or filesystem imports. Derive `overall`, `code`, Chinese `summary`, `next_step`, and rows inside the model. Use one explicit freshness operation:

```python
def current(self, *, evidence_age: timedelta | None, max_age: timedelta) -> "PublicConnectivityStatus":
    stale = self.observed_at is None or evidence_age is None or evidence_age > max_age
    return replace(self, freshness=FreshnessState.STALE if stale else FreshnessState.FRESH)
```

`evidence_age` comes only from elapsed monotonic time owned by the provider. UTC timestamps remain a
human-readable projection and never decide whether evidence is current.

The projection must serialize enums by `.value`, timestamps in UTC ISO-8601, safe scalar evidence only, and a fixed `supported_actions` list of `refresh`, `full_check`, `export_diagnostics`.

- [x] **Step 4: Run the model tests GREEN and lint the two files**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_public_connectivity.py
.\.venv\Scripts\ruff.exe check backend_manager\public_connectivity.py tests\test_public_connectivity.py
```

Expected: both commands exit zero.

- [x] **Step 5: Commit the independently reviewable model**

```powershell
git add desktop/backend_manager/public_connectivity.py desktop/tests/test_public_connectivity.py
git commit -m "feat(desktop): add public connectivity status model"
```

### Task 2: Exact SCM and cloudflared loopback probes

**Files:**
- Create: `desktop/backend_manager/cloudflared_contract.py`
- Create: `desktop/backend_manager/windows_cloudflared_service.py`
- Create: `desktop/backend_manager/cloudflared_probe.py`
- Create: `desktop/tests/test_cloudflared_probe.py`

**Interfaces:**
- Consumes: optional `ManagedConnectorExpectation` supplied by the provider; otherwise the fixed official service name and fixed official default ports.
- Produces: `CloudflaredProbeResult`, `probe_cloudflared(expectation=None, service_reader=..., transport=...)`, `WindowsCloudflaredServiceReader.read_exact(name)`, and `LoopbackCloudflaredTransport.read_json(port, path)`.

- [x] **Step 1: Write failing adapter tests with fake native and HTTP boundaries**

Cover exact service missing, service running, service ImagePath/argv mismatch, service account/start/failure-action mismatch, external `/ready` never managed, multiple conflicting diagnostic identities, connector down, partial connection degradation, tunnel/connector mismatch, malformed UUID/schema, body oversize, redirect, proxy disablement, non-loopback rejection, and timeout mapped to safe unknown/down evidence.

Pin the official response contracts:

```python
ready = {"status": 200, "readyConnections": 4, "connectorId": CONNECTOR_ID}
tunnel = {"tunnelID": TUNNEL_ID, "connectorID": CONNECTOR_ID, "connections": [{}, {}, {}, {}]}
```

Assert that `repr(result)` and `result.to_safe_evidence()` contain neither UUID, executable path, token-file path, argv, raw connection object, nor an injected secret marker.

- [x] **Step 2: Run the adapter tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_cloudflared_probe.py
```

Expected: collection fails because `backend_manager.cloudflared_probe` does not exist.

- [x] **Step 3: Implement bounded loopback transports and parsers**

Build the opener only as:

```python
urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
```

Accept only `127.0.0.1`, integer ports `1..65535`, and paths from the fixed set `{ "/ready", "/diag/tunnel" }`. Read at most 8 KiB plus one byte, use sub-second per-request timeouts, parse exact JSON types, canonicalize UUIDs with `uuid.UUID`, and retain IDs only inside the comparison scope.

- [x] **Step 4: Implement native exact-name SCM observation**

Use `OpenSCManagerW`, `OpenServiceW`, `QueryServiceStatusEx`, `QueryServiceConfigW`, and `QueryServiceConfig2W(SERVICE_CONFIG_FAILURE_ACTIONS)`. Parse ImagePath with `CommandLineToArgvW`; never invoke `sc.exe`, PowerShell service text parsing, WMI wildcard process queries, or a subprocess. Convert raw service state to the model and compare a protected expectation in memory.

When no protected expectation exists, query only exact `Cloudflared` and scan only ports `20241..20245`; any observation is `external_unmanaged`, never `managed`. Managed ownership requires every expected SCM and diagnostic identity comparison to pass.

- [x] **Step 5: Run focused GREEN, cross-platform compile, and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_cloudflared_probe.py
.\.venv\Scripts\python.exe -m compileall backend_manager\cloudflared_probe.py
.\.venv\Scripts\ruff.exe check backend_manager\cloudflared_probe.py tests\test_cloudflared_probe.py
```

Expected: all commands exit zero on Windows without mutating SCM.

- [x] **Step 6: Commit the probe boundary**

```powershell
git add desktop/backend_manager/cloudflared_probe.py desktop/tests/test_cloudflared_probe.py
git commit -m "feat(desktop): add readonly cloudflared probes"
```

### Task 3: Public product and boundary probe

**Files:**
- Create: `desktop/backend_manager/public_endpoint_probe.py`
- Create: `desktop/tests/test_public_endpoint_probe.py`

**Interfaces:**
- Consumes: `PublicEndpointContext(public_origin, session)` where the `ProductSession` token is `repr=False` and optional.
- Produces: `PublicEndpointProbeResult(public, boundary, code)`, `probe_public_endpoint(context, transport=...)`, and `BoundedHttpsTransport.get(path, session_token=None)`.

- [x] **Step 1: Write failing public-probe contract tests**

Use a fake transport that records method/path/header metadata without retaining Authorization values. Cover:

- missing public origin -> `unconfigured`;
- missing origin with unavailable installation-health authority -> `unknown`, not `unconfigured`;
- Backend-canonicalized non-loopback IPv4/IPv6 HTTPS origins -> probeable;
- HTTP/userinfo/path/query/fragment -> fail-closed wrong configuration;
- valid anonymous health -> `reachable_unverified`;
- valid health plus matching auth-check metadata, `scope=app`, and `credential_state=current` -> `authenticated_reachable`;
- matching auth metadata with `credential_state=grace` -> `reachable_unverified`, never authenticated green;
- auth 401 after valid health -> `reachable_unverified`;
- auth 200 with malformed schema or mismatched account/ledger/device/role -> `wrong_product`;
- public health network failure -> `unreachable`;
- a forbidden path returning 200 -> boundary `violation`;
- all forbidden paths returning only 401/403/404/405 -> boundary `safe`;
- redirects/timeouts -> boundary `unknown`;
- malformed or non-object JSON keeps the received HTTP status while making only the payload unavailable;
- no request uses a real UploadLink capability or a mutating HTTP method;
- token markers are absent from exceptions, results, repr, and recorded URL/path values.

- [x] **Step 2: Run the probe tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_public_endpoint_probe.py
```

Expected: collection fails because `backend_manager.public_endpoint_probe` does not exist.

- [x] **Step 3: Implement normalized HTTPS and bounded reads**

Consume the Backend-canonicalized HTTPS-origin contract, including canonical non-loopback IPv4/IPv6 literals, while rejecting loopback, unspecified, userinfo, path, query, and fragment forms. Disable proxies and redirects, use the default TLS verifier, accept only fixed GET paths, cap each body at 8 KiB, cap the complete check at sixteen requests and eight seconds, and parse JSON only after a matching JSON media type.

Use exact safe paths:

```python
_FORBIDDEN_GET_PATHS = (
    "/owner",
    "/desktop/session/revoke",
    "/api/health/installation",
    "/api/status/private",
    "/api/admin/devices",
    "/api/maintenance/learning-status",
    "/api/bootstrap/owner",
    "/u/ticketbox-public-probe-no-capability",
    "/static/uploads/ticketbox-public-probe-missing",
)
```

Probe `/api/health` first, anonymous `/api/auth/check` for the boundary, then authenticated `/api/auth/check` only when a Desktop app session exists. Match only non-secret local session metadata and require `credential_state=current`; never serialize the token. A matching `grace` token is still valid for Backend in-flight completion, but this new probe reports only `reachable_unverified`.

- [x] **Step 4: Run focused GREEN and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_public_endpoint_probe.py
.\.venv\Scripts\ruff.exe check backend_manager\public_endpoint_probe.py tests\test_public_endpoint_probe.py
```

Expected: both commands exit zero.

- [x] **Step 5: Commit the public boundary probe**

```powershell
git add desktop/backend_manager/public_endpoint_probe.py desktop/tests/test_public_endpoint_probe.py
git commit -m "feat(desktop): verify public product boundary"
```

### Task 4: Asynchronous provider and runtime composition

**Files:**
- Create: `desktop/backend_manager/public_connectivity_provider.py`
- Create: `desktop/tests/test_public_connectivity_provider.py`

**Interfaces:**
- Consumes: `RuntimeConfigProvider`, `probe_cloudflared`, `probe_public_endpoint`, `load_product_session`, `load_rebind_recovery`, monotonic/UTC clocks, and an executor factory.
- Produces: `PublicConnectivityProvider.snapshot()`, `request_refresh(full=False) -> int`, `run_monitor(stop_event)`, `shutdown()`, and `build_public_connectivity_provider(runtime_provider)`.

- [x] **Step 1: Write failing provider tests**

Assert:

- `snapshot()` performs no SCM, HTTP, WinCred, sleep, DNS, or runtime refresh;
- initial state is stale unknown;
- local refresh maps the existing runtime's exact health projection to origin state;
- full refresh is the only path that loads a Desktop session and runs the public probe;
- an older slow generation cannot overwrite a newer completed generation;
- a cached full public result ages stale after 60 seconds even while local checks continue;
- cached public/boundary evidence is reused only for the same attested public origin and authority state;
- an overlapping refresh retires reusable public/boundary evidence before the newer generation is scheduled;
- unavailable Backend authority remains public `unknown` rather than becoming `unconfigured`;
- wall-clock jumps do not make evidence stale or fresh; only monotonic elapsed age does;
- no-session full check remains reachable-unverified;
- a completed recovery proof blocks a predecessor primary session, while a primary matching the derived promoted session remains usable;
- monitor cadence is ten seconds and does not overlap an in-flight generation;
- probe exceptions commit safe unknown evidence without exception text;
- shutdown cancels queued work and rejects new requests without an indefinite wait.

Use controlled events rather than sleeps for the race test:

```python
older_started = threading.Event()
release_older = threading.Event()
newer_committed = threading.Event()
```

- [x] **Step 2: Run the provider tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_public_connectivity_provider.py
```

Expected: collection fails because the provider module does not exist.

- [x] **Step 3: Implement cache, generation, and monitor semantics**

Use a lock-protected cached status and `ThreadPoolExecutor(max_workers=2, thread_name_prefix="ticketbox-public-connectivity")`. Increment `_requested_generation` before submitting. Commit only when:

```python
if generation == self._requested_generation and not self._shutdown:
    self._status = assembled
```

The runtime context loader calls `runtime_provider.current()` off-thread and maps its attested
`RuntimeStatus` to the origin axis. The Backend canonicalizes its service-owned runtime setting into
the loopback installation-health contract; `RuntimeStatus.public_origin` carries that value only
inside the Manager process, including installed mode where `ManagerConfig.public_base_url` is
intentionally `None`. A `ProductSession` is loaded only for `full=True` and a present attested
origin. The explicit `mobile_endpoint_state` distinguishes authoritative `local_only` from a lost
authority projection; cached public evidence is keyed to both that state and the exact origin.
`AppController` brackets every operation that may change Backend or WinCred ProductSession truth with
`begin_product_session_mutation()` / `end_product_session_mutation()`. Both edges advance the
generation, clear the cached public/boundary result, and publish `stale + unknown`; refresh requests
inside the window are not scheduled. Thus a full check cannot select an intermediate session subject,
and neither committed-response loss nor WinCred save/delete failure leaves old bearer evidence live.
For durability across the end of that window and Manager restart, the context loader also reads the
rebind recovery slot: when it contains a completed ceremony, a primary bearer is admitted only if it
matches the successor deterministically derived from that proof. A predecessor accepted only by
Backend rotation grace therefore remains unauthenticated until reconciliation promotes the successor.
The pair gate likewise refuses to delete or overwrite a completed recovery proof unless the current
primary equals that derived successor and any recorded predecessor revoke has completed. Backend's
terminal activation-replay 401 may retire an impossible ceremony; the auth-check `credential_state`
still prevents any surviving grace predecessor from being promoted to authenticated green.
Current installed configuration supplies no `ManagedConnectorExpectation`.

- [x] **Step 4: Run provider GREEN, combined model/probe tests, and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_public_connectivity.py tests\test_cloudflared_probe.py tests\test_public_endpoint_probe.py tests\test_public_connectivity_provider.py
.\.venv\Scripts\ruff.exe check backend_manager\public_connectivity*.py backend_manager\cloudflared_probe.py backend_manager\public_endpoint_probe.py tests\test_public_connectivity*.py tests\test_cloudflared_probe.py tests\test_public_endpoint_probe.py
```

Expected: all commands exit zero.

- [x] **Step 5: Commit the coordinator**

```powershell
git add desktop/backend_manager/public_connectivity_provider.py desktop/tests/test_public_connectivity_provider.py
git commit -m "feat(desktop): coordinate public connectivity reads"
```

### Task 5: AppController, control routes, and startup lifetime

**Files:**
- Modify: `desktop/backend_manager/app_controller.py`
- Modify: `desktop/backend_manager/control_server.py`
- Modify: `desktop/backend_manager/manager_startup.py`
- Modify: `desktop/tests/test_app_controller.py`
- Modify: `desktop/tests/test_control_auth.py`
- Modify: `desktop/tests/test_manager_startup.py`

**Interfaces:**
- Consumes: `PublicConnectivityProvider` from Task 4.
- Produces: AppController `refresh_public_connectivity()` and `run_full_public_connectivity_check()`, `/api/refresh_public_connectivity`, `/api/run_full_public_connectivity_check`, and status key `public_connectivity`.

- [x] **Step 1: Write failing controller and route tests**

Inject a fake public provider and assert:

```python
assert controller.status()["public_connectivity"]["schema"] == "ticketbox-public-connectivity-v1"
assert "tunnel" not in controller.status()
assert "public_endpoint_state" not in controller.status()
```

Assert each new POST requires the existing control token, same-origin/Fetch metadata, empty body, and manager-not-shutting-down state. Assert it schedules the correct provider mode and returns status without waiting for the probe. Assert unsupported mutation names return 404 and are absent from `_ACTIONS`.

In startup tests, inject a fake builder/provider and assert initial local refresh, a separate monitor thread, stop signaling, provider shutdown, and bounded join.

- [x] **Step 2: Run the three focused files and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_app_controller.py tests\test_control_auth.py tests\test_manager_startup.py
```

Expected: new assertions fail because the provider is not wired and the routes do not exist.

- [x] **Step 3: Inject the provider and retire duplicate consumers**

Add an optional provider constructor argument with a cache-only unknown implementation for existing unit tests. `status()` reads one snapshot and publishes only `public_connectivity`; keep `mobile_endpoint_state` because it is a separate Backend capability, but remove `tunnel` and the duplicate `public_endpoint_state` key.

The action methods contain only:

```python
def refresh_public_connectivity(self) -> None:
    self._public_connectivity.request_refresh(full=False)

def run_full_public_connectivity_check(self) -> None:
    self._public_connectivity.request_refresh(full=True)
```

- [x] **Step 4: Wire CSRF routes and lifetime ownership**

Add only `refresh_public_connectivity` and `run_full_public_connectivity_check` to the fixed action tuple and Controller protocol. In `run_owned_manager`, build and inject the provider, schedule one local refresh after the control server binds, start its monitor thread, set the common stop event on exit, call provider shutdown, and join its thread with the existing five-second ceiling.

- [x] **Step 5: Run focused GREEN and lint touched Python files**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_app_controller.py tests\test_control_auth.py tests\test_manager_startup.py
.\.venv\Scripts\ruff.exe check backend_manager\app_controller.py backend_manager\control_server.py backend_manager\manager_startup.py tests\test_app_controller.py tests\test_control_auth.py tests\test_manager_startup.py
```

Expected: all commands exit zero.

- [x] **Step 6: Commit the stable Manager API integration**

```powershell
git add desktop/backend_manager/app_controller.py desktop/backend_manager/control_server.py desktop/backend_manager/manager_startup.py desktop/tests/test_app_controller.py desktop/tests/test_control_auth.py desktop/tests/test_manager_startup.py
git commit -m "feat(desktop): expose public connectivity status"
```

### Task 6: Public Connectivity Manager UI

**Files:**
- Modify: `desktop/backend_manager/ui.html`
- Modify: `desktop/tests/test_ui_contract.py`
- Modify: `desktop/tests/test_ui_browser_layout.py`

**Interfaces:**
- Consumes: the server-derived `public_connectivity.summary`, `next_step`, `detail_rows`, `supported_actions`, and `in_progress` fields.
- Produces: one accessible `公网连接` card and the three permitted controls.

- [x] **Step 1: Write failing static and browser UI tests**

Assert exact title/subtitle copy, row labels, button actions, keyboard focus, narrow viewport layout, and no horizontal overflow. Assert forbidden words/actions such as install/start/stop/restart/repair/update/UAC for cloudflared are absent from the card. Assert JavaScript does not derive overall state from the individual axes. A rejected/non-2xx Manager status or permanently pending status/body/ancillary read replaces any prior healthy public-connectivity card with the neutral unknown skeleton within the two-second refresh deadline; a prompt ancillary product fetch, HTTP, JSON-body, or schema failure retires prior product metadata/entry points, degrades only that product surface, and releases the refresh lock. The schema oracle must use an iterable ledger row with an out-of-domain role so removing the validator cannot fall into an unrelated `.map()` exception and still pass.

- [x] **Step 2: Run UI tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_ui_contract.py tests\test_ui_browser_layout.py
```

Expected: the new card and controls are missing.

- [x] **Step 3: Implement a projection-driven card**

Render the heading and subtitle exactly:

```html
<h2>公网连接</h2>
<p class="card-subtitle">由 Cloudflare Tunnel 提供</p>
```

Render `summary`, `next_step`, and `detail_rows` as text with `textContent`. Apply one two-second deadline across `/api/status`, its JSON body, and ancillary product-session/ledger refreshes. Show a neutral unknown skeleton when Manager status rejects/is non-2xx, its body rejects, or the shared deadline expires, so a previously healthy card cannot remain green after loss of status authority. Keep prompt ancillary product failures product-specific: malformed/non-object JSON and consumer-invalid session/ledger schemas are failures, clear old options and entry points, and release the refresh lock without erasing the successful Manager projection. Accept only canonical `owner`, `member`, and `viewer` roles from both product consumers. Build buttons only from the intersection of the fixed UI map and server `supported_actions`; disable refresh/full-check while `in_progress`, but keep diagnostic export independent. Reuse existing card, row, button, focus, and responsive tokens.

- [x] **Step 4: Run UI GREEN and the existing Edge layout lane**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_ui_contract.py tests\test_ui_browser_layout.py tests\test_web_bff_edge_e2e.py
```

Expected: all collected tests pass; an unavailable Edge runtime may skip only tests already marked with the repository's existing skip condition.

- [x] **Step 5: Commit the read-only UI**

```powershell
git add desktop/backend_manager/ui.html desktop/tests/test_ui_contract.py desktop/tests/test_ui_browser_layout.py
git commit -m "feat(desktop): render public connectivity backstage"
```

### Task 7: Privacy-safe diagnostic projection

**Files:**
- Modify: `desktop/backend_manager/diagnostic_bundle.py`
- Modify: `desktop/tests/test_diagnostic_bundle.py`

**Interfaces:**
- Consumes: `status["public_connectivity"]` from Task 5.
- Produces: `diagnostics.json.runtime.public_connectivity` with a closed scalar/nested allowlist.

- [x] **Step 1: Write failing adversarial diagnostic tests**

Supply a valid safe projection plus malicious sibling/nested values named and valued as URL, token, Authorization, tunnel/connector UUID, ImagePath, argv, account/device identifiers, log, certificate, and absolute path. Assert the ZIP bytes and decoded JSON contain only:

```python
{
    "overall", "code", "freshness", "observed_at", "public_checked_at",
    "ownership", "service", "connector", "origin", "public", "boundary",
    "managed_action", "cloudflared_version", "connection_count",
    "service_identity_match", "binary_identity_match", "tunnel_identity_match",
}
```

Also assert the retired scalar `public_endpoint_state` is absent.

- [x] **Step 2: Run diagnostic tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_diagnostic_bundle.py
```

Expected: the safe nested projection is missing or the retired scalar is still present.

- [x] **Step 3: Implement a closed nested sanitizer**

Validate the outer schema string, enum value sets, timestamp shape, integer count bounds, version length/pattern, and boolean-or-null match fields. Construct a new dict key by key; never copy an arbitrary nested mapping. Keep the existing top-level privacy declaration and add no raw logs or paths.

- [x] **Step 4: Run diagnostic GREEN and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_diagnostic_bundle.py
.\.venv\Scripts\ruff.exe check backend_manager\diagnostic_bundle.py tests\test_diagnostic_bundle.py
```

Expected: both commands exit zero.

- [x] **Step 5: Commit the diagnostic projection**

```powershell
git add desktop/backend_manager/diagnostic_bundle.py desktop/tests/test_diagnostic_bundle.py
git commit -m "feat(desktop): sanitize public connectivity diagnostics"
```

### Task 8: Full verification, real-Windows read-only evidence, and closure record

**Files:**
- Modify: `docs/superpowers/specs/2026-09-01-public-connectivity-stage1.md` only if implementation evidence reveals a contract clarification that remains within Stage 1.
- Create: `docs/runbook/PUBLIC_CONNECTIVITY_BACKSTAGE.md`
- Modify: `.claude/HANDOFF.md`

**Interfaces:**
- Consumes: all Stage 1 modules and tests.
- Produces: operator-safe state explanations, exact validation commands/results, real-Windows read-only observations, and a short handoff that keeps Stage 2 on HOLD.

- [x] **Step 1: Run the complete Desktop CI-equivalent gate**

```powershell
.\.venv\Scripts\python.exe -m compileall backend_manager tests
.\.venv\Scripts\ruff.exe check backend_manager tests
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all commands exit zero with no unexpected skip or warning topology.

- [x] **Step 2: Run focused non-leak and forbidden-mutation audits**

```powershell
rg -n "cloudflared.*(install|start|stop|restart|repair|update)|tunnel.*token|Cloudflare.*API|config\.ya?ml" desktop/backend_manager desktop/tests
rg -n "public_base_url|tunnelID|connectorID|ImagePath|Authorization|session_token" desktop/backend_manager/public_connectivity.py desktop/backend_manager/diagnostic_bundle.py desktop/backend_manager/ui.html
```

Expected: the first command finds only test assertions/copy that rejects those actions; the second finds no secret-bearing projection or UI output path. Inspect every match rather than accepting count alone.

- [x] **Step 3: Run read-only Windows observations**

Use the shipped probe from the isolated worktree without a protected expectation. Record only safe output: exact `Cloudflared` service state, ownership classification, connector state/count, origin state, public/boundary states, freshness, and stable code. Confirm the already-observed external connector remains `external_unmanaged` and cannot become `managed`. Do not mutate SCM, tasks, processes, files, registry, credentials, tunnel configuration, or networking.

- [x] **Step 4: Restart only the Desktop Manager test fixture and verify cache reset**

Start and stop the repository's existing Manager test fixture, not cloudflared or Ticketbox lifecycle services. Assert the new instance begins stale/unknown and acquires only newly observed evidence; it must not carry a prior healthy cache across process restart.

- [ ] **Step 5: Write the runbook and short handoff**

Document the state meanings, supported actions, privacy boundary, 10-second local cadence, 60-second complete-evidence staleness, read-only troubleshooting, and the exact Stage 2 HOLD list. Update `.claude/HANDOFF.md` with exact branch/HEAD/tree, commands/results, current Stage 1 gate state, and the next bounded action.

- [ ] **Step 6: Re-run the exact final-head gate**

After documentation changes, rerun:

```powershell
git status --short
git rev-parse HEAD
git rev-parse "HEAD^{tree}"
.\.venv\Scripts\python.exe -m compileall backend_manager tests
.\.venv\Scripts\ruff.exe check backend_manager tests
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: only intended files are present before commit; all verification commands exit zero.

- [ ] **Step 7: Commit the evidence package**

```powershell
git add docs/runbook/PUBLIC_CONNECTIVITY_BACKSTAGE.md .claude/HANDOFF.md docs/superpowers/specs/2026-09-01-public-connectivity-stage1.md docs/superpowers/plans/2026-09-01-public-connectivity-stage1.md
git commit -m "docs: record public connectivity backstage evidence"
```

- [ ] **Step 8: Validate the construction closure receipt**

Generate a response-only engineering-construction receipt for `ticketbox-public-connectivity-20260901-001`, include the recorded failed attempts and rework, test/real-Windows evidence, final exact HEAD/tree, unresolved gates, and held follow-up `managed-public-connector`. Validate it with the construction-corpus validator before reporting its state.

- [ ] **Step 9: Apply the closure rule**

Declare `PUBLIC_CONNECTIVITY_BACKSTAGE = CLOSED` only if the complete Stage 1 automated, privacy, exact-final-head, and applicable real-Windows read-only gates all pass. If any gate is unavailable or fails, keep Stage 1 open and name that exact gate. Always report `MANAGED_PUBLIC_CONNECTOR = HOLD`.

---

## Self-review record

- Spec coverage: every Gmail Stage 1 state axis, ownership rule, probe boundary, AppController/UI/diagnostic responsibility, automated matrix, real-Windows lane, and closure condition maps to a task above.
- Scope: no task mutates cloudflared, Cloudflare account state, lifecycle/installer state, Machine Secrets, Release Manifests, SCM, Scheduled Tasks, registry, or privileged IPC.
- Type consistency: Tasks 1 through 7 use one `PublicConnectivityStatus -> to_projection() -> AppController public_connectivity -> UI/diagnostic` path; probe IDs and secrets never cross into that projection.
- Execution mode: this session must use `superpowers:executing-plans` inline because no user request authorized subagent delegation.
