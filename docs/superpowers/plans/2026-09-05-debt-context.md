# External-debt context implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is one tightly coupled vertical task; the main agent owns production writes.

**Goal:** A person can record why an external obligation exists and read that context in Web and Android without losing it on a rejected submission.

**Architecture:** The nullable Debt note is the only stored context. Existing create/idempotency and query owners carry it; clients render plain text. No separate metadata writer, chat, or offline queue.

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy/Alembic, native Jinja forms, Kotlin/Compose and existing DTO mappers.

**Spec:** `docs/current/TICKETBOX_CURRENT_PRODUCT_ATLAS.md`, External-debt context construction section, derived from the current Goal and final product/construction contracts.

## Global Constraints

- Optional plain text, maximum 500 characters; blank becomes no note.
- Notes inherit Debt access; principal, repayments, member acceptance and OCC meanings do not change.
- Preserve identity, ledger and existing request fingerprint ownership; no second writer.
- Current Android Debt creation is online only. Do not label it Outbox-enabled.
- No local PostgreSQL, Android or installer test runs. Exact cloud candidate owns runtime evidence.
- Windows Fresh G2 CLOSED; restore, repair, upgrade and complete lifecycle HOLD.

### Task 1: Persist and consume external-debt context

**Files:**
- Backend: `app/models/debt.py`, `app/schemas/_debts.py`, `app/services/debt_service/_create.py`, `app/services/debt_service/_query.py`, migration after `20260901_0001`.
- Packaging declaration only: `distribution/windows/payload/release-manifest.json` must name the same new schema head. The existing build guard compares it with the frozen generation program; no installer or lifecycle implementation changes.
- Web: `app/routes/web_debt_create.py`, `app/routes/web_debts.py`, `app/templates/web/debt_new.html`, `app/templates/web/debt_detail.html`.
- Android: `DebtDto.kt`, `Debt.kt`, `DebtMappers.kt`, `DebtListViewModel.kt`, `DebtListDraftActions.kt`, `DebtListScreen.kt`, `DebtDetailScreen.kt`, `strings_stats_budget.xml` and matching existing tests. Detail context reuses the existing external-debt summary, so the detail chrome need not change.
- Tests: `backend/tests/test_web_debt_actions.py`, existing debt API and Android mapper/ViewModel tests; generated OpenAPI from the actual changed schema.

**Interfaces:**
- `DebtCreateRequest.note: str | None`, `DebtResponse.note: str | None`.
- Kotlin `DebtDraft.note: String?`, `DebtCreateRequestDto.note: String?`, `DebtDto.note: String?`, `Debt.note: String?`, and `DebtDraftUi.note: String`.
- All new optional Kotlin fields default to null (UI to empty string), preserving existing constructors and old response decoding.

- [ ] Extend the real native form journey first. Post `note="出差垫款 <行程说明>"`; require escaped detail content, identical replay, canonical API note and a 422 on changed note with the same key. Add a note to the invalid-JPY form and require it remains visible. Push test-only candidate and observe actual PostgreSQL RED in cloud. In parallel, run only `test_create_note_is_optional_and_bounded` via `runpy` without pytest database fixtures: the unsupported `note` request is the narrow pre-implementation RED; the native PostgreSQL journey remains a distinct cloud gate.
- [ ] Add nullable `sa.Text()` column `debts.note`; no backfill or alternate store. Add request `note: str | None = Field(default=None, max_length=500)` and optional response `note: str | None = None`. Store `note=(payload.note or "").strip() or None` in `create_debt`; publish `note=debt.note` in the existing response builder. Existing `payload.model_dump` includes it in the shared fingerprint.
- [ ] Add Web `note: str = Form(default="")`, preserve it in `values`, and pass it to `_create_payload` and `DebtCreateRequest`. Replace the old 80-character input with an escaped 500-character textarea. Add `note` to the existing detail projection and render an optional plain-text section using semantic product styles, without `safe` or raw HTML.
- [ ] Carry `note = note` through DTO → domain and `note = note?.trim()?.ifBlank { null }` through draft → request. Add `DebtDraftField.Note`; editing it clears only validation error. Submit `note = draft.note`, preserve the state on failure and show the note input and optional detail text. Do not modify the online-only repository publication protocol.
- [ ] Extend existing mapper/state tests: nonblank note round-trips, blank becomes null, failed create retains note; API rejects 501 characters and accepts omitted/null legacy payloads. Use the real generated OpenAPI command, affected Ruff and `git diff --check` locally. All PostgreSQL/JVM/connected/migration execution runs on exact cloud head.
- [ ] Perform one bounded review of the current postcondition, privacy, fingerprint and consumers. Fix only confirmed current-slice blockers; update this map and the PR with actual executions versus skips. Merge only after exact candidate qualification, then qualify exact merged main. This slice does not complete the full product Goal.

## Execution state

Test-only `6f1b4fe2` reproduced both missing-context native consumers in cloud CI `33962984089`. The pure request contract failed on unsupported `note`, then passed after schema implementation in under one second without a database connection. Backend, migration, Web and Android changes and matching tests are implemented. Scoped Ruff, generated OpenAPI drift, native template compilation and XML parsing pass locally. PostgreSQL, migration and Android runtime qualification are pending; no local heavy lanes have run.

The bounded review of `b3408fff..d38ebab2` found one P2: a browser-valid 500-character multiline textarea submits as 501 characters after CRLF expansion and was rejected. FIX: normalize form newlines in the Web adapter before the existing schema boundary. A pure adapter test reproduced `string_too_long` before the fix and then passed CRLF, CR and LF boundaries in about one second, without a database connection. The existing native PostgreSQL journey now submits a full-length CRLF note and replays its LF form, preserving the same command fingerprint and escaped detail. The packaging declaration is aligned to the new schema head; no lifecycle implementation changed. Review confirmation of these small follow-ups and exact integration qualification remain open.
