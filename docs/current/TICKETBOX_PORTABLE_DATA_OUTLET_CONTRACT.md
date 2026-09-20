# Complete portable product data outlet

This delivery follows the active full-product Goal and the final 2026-08-26
Product contract §6.2–6.10, §7 and §18, within the post-G2 P1/P2 stage. Codex
has delegated product and implementation responsibility within those boundaries.
The existing product atlas remains the complete delivery plan. This document
defines the next portable-export task; it does not replace either architecture
contract or open Windows lifecycle actions.

Preparation started from the isolated original-integrity candidate. PR #424 is
now protected-squash merged at `50a128d185dbcf92689736cfd51e3eef25599dac`, with a
source tree identical to its fully qualified final candidate `019711bc`. This
outlet integrates that main baseline, including the reviewed original-read and
offline-continuation fixes; its own final candidate still requires qualification.

## User result and retained capabilities

An authorized person can take away the ledger's persisted product data, history,
relationships and available original evidence in an ordinary downloadable package.
The package explains its scope and time, preserves source identities and money/time
meaning, and identifies evidence that could not be included. It can be inspected
without a running Ticketbox installation. It does not claim to be an installation
restore image or executable replay of past commands.

Keep the existing filtered CSV export, native CSV event continuation, all original
downloads, ordinary use during export, and existing domain ownership. Missing or
damaged evidence must not prevent taking away the surviving financial and other
business records. Export is read-only: it never confirms suggestions, adopts a
legacy digest, settles cleanup, changes roles or reassigns an intent.

## Meaning and delegated choices

The contract forces completeness across the actual product, rather than only
confirmed expense projections. Reusing the filtered CSV alone is insufficient.
The current full-backup implementation also cannot substitute: it requires a
qualified host action, and its original copier rejects absent/unverified files.

Within the delegated scope, the portable outlet will provide a versioned, openly
documented data package with a human-readable explanation, structured records and
their relationships, and the available original files. Existing analytical CSV is
retained as a useful readable projection. No proprietary runtime is required to
open the package. The implementation should use ordinary formats and the existing
snapshot/file primitives, not introduce a general export platform.

Completeness has two independent meanings. The structured business snapshot must
be complete for the advertised authorization scope; a query, encoding, storage or
limit failure cannot become a successful truncated export. Original-file coverage
is reported separately, per reference: verified, present but historically
unverified, missing, mismatched, deliberately cleaned, or temporarily unreadable.
A thumbnail cannot satisfy a missing original. Every included file has its actual
size and digest; a newly measured digest does not become historical authority.

The person selects an authorized ledger. All of that ledger's applicable statuses
and retained history are included; current screen filters, pagination, current
month, archive visibility and active-only defaults cannot silently restrict it.
Cross-ledger links retain the snapshots and references the selected ledger is
entitled to see, without following them into another ledger's private records.
Read authorization follows the current identity/membership owner. The new outlet
does not confer write permission or replace existing local CSV access.

The package distinguishes ledger records from explicitly named `account_*`
relationship snapshots. The latter retain the exporter's account-wide split inbox
and authorized cross-ledger debt/repayment/proposal views without revealing the
other party's ledger, member or expense identifiers. Only an accepted inbox result
in the selected ledger carries a local expense link. Selected-ledger sent
invitations retain the sender's existing actor-scoped visibility; other members'
accepted source relationships retain only the existing narrow agreement/debt
reference projection. Repayment drafts remain restricted to their creating actor.
These participant snapshots are not a complete copy of the other ledger.
`account_debt_balances` preserves the existing participant owner's public balance
and settlement observation in the same read snapshot; private adjustments and
forgiveness rows remain outside this account view. The export adapter does not
invent a second balance fold.

Governance audit follows the existing member-management permission. Ledger-owner
membership does not grant the separate local Owner Console AI/operational audit
permission. Task observations retain only the actor's selected-ledger public
state/result, never execution input or raw exception text that may contain host
paths. Accepted operations are historical records, restricted by resource
visibility. An upload receipt whose personal task access cannot be established
retains its accepted business resource reference with an explicit
`response_body_omission_reason`; its private task-bearing response body is omitted.
Runtime import claims, credential material, machine settings and AI anonymization
maps are not business record collections. Authorized account/device references
carry only the identities needed to interpret exported records.

## Required content and relations

| Product responsibility | Required retained data |
| --- | --- |
| Ledger and interpretation | Ledger identity and settings, authorized member/actor references, calendar revisions, persisted money/currency/FX evidence needed to interpret records. Identity references do not carry active credentials. |
| Capture and review | Expenses in all retained states, source/provenance, stored OCR/rule suggestions and learning decisions, duplicate decisions; CSV batches, source rows and event-to-fact mappings, preserving suggestion versus accepted fact. |
| Financial facts | Expense items, splits and tags; financial revisions, reasons and actors; root expense to refund/reversal/offset facts and revisions, including voided history. Amounts and dates retain their recorded precision and meaning. |
| Relationships | Split invitation agreement snapshots and accepted links; debts, repayments, adjustments, forgiveness, debt/repayment voids; proposals and supersession/settlement links; retained repayment drafts. A current balance is not a replacement for events. |
| Planning | Budgets/categories, goals and debt links, income plans and revisions, recurring series, occurrences, payment links and occurrence revisions; paused/archived states and history that actually exists. No missing historical revision is fabricated. |
| Reference library | Categories, merchants/aliases, tags and references, rules and application batches/changes, retained rename/merge/delete/undo evidence. Stable references remain resolvable inside the package. |
| Original evidence | Current references, recorded/observed identity, cleanup and replenishment evidence, included original files and distinct derived-file meaning. Old references in retained cleanup/history remain distinguishable from the current original. |
| Accepted operations and history | Applicable retained business audit and accepted-result evidence, as history only. Never produce a runnable queue or revive an expired authorization. |

The implementation must inventory the actual model fields and relation edges
before choosing record adapters. ORM table enumeration alone does not define
product scope. Conversely, omitting a retained business field solely because no
current UI displays it is not a valid completeness policy.

## Snapshot, privacy and file boundaries

- Read one consistent structured-data snapshot. Do not assemble different moments
  from independently refreshed domain endpoints. Avoid holding a global writer
  fence for this ordinary read task.
- Copy evidence through the existing bounded resolver and stable/verified reader.
  Bind each file observation to the reference and expected identity captured for
  that export. Explain a concurrent cleanup or replacement as an observation;
  never silently substitute another file or call the package a point-in-time
  complete filesystem backup.
- Bound work and temporary storage. A resource limit fails explicitly or offers
  an explicit supported continuation; it never silently omits records. Disconnect,
  cancellation and failed packaging release only this request's temporary files.
- Do not include tokens, secrets, credential hashes, enrollment material, provider
  credentials, private host configuration or absolute machine paths. Retain the
  business identity and provenance needed to interpret the authorized records.
  User-authored business text must not be scrubbed merely for matching a keyword.
- Server output cannot include Android Room/FileStore or browser drafts that have
  not reached the server. The UI and package state that boundary plainly and keep
  the existing client intents intact. Successfully accepted server results remain
  part of the server snapshot even when the originating client lost the ACK.

## Owners, consumers and impact before implementation

| Existing owner / consumer | Required result |
| --- | --- |
| Identity, ledger scope and read authorization | Current actor and scope validated by existing owners; viewer/read and cross-ledger boundaries exercised explicitly. |
| Domain facts, revisions and references | Export adapters read established authorities, including retained states, without reproducing financial folds or command rules. |
| `stats_service.export_confirmed_csv` and reports | Preserve their current filtered analytical use; label them as projections inside any larger package. |
| Original read and backup-copy primitives | Reuse stable-byte and digest work; adapt coverage semantics explicitly instead of claiming the complete-backup copier already fits. |
| Web import/export and data-quality surfaces | A discoverable export action, understandable scope/result and actionable partial evidence; retain existing CSV and original controls. |
| Owner and Desktop Backstage | Reach the product outlet through the existing authenticated product path; do not add a second export or lifecycle owner. |
| Android and Shortcut | Preserve their existing capture/offline tasks and the distinction between local unsubmitted intent and accepted server data; do not require identical export UI on every endpoint. |
| Packaging and real DB verification | Include the actual export implementation; prove consistent snapshots, relation completeness, access boundaries and original-file outcomes on the exact candidate. |

## Exclusions and completion

This task does not implement full backup/restore, migration into another running
installation, re-enrollment, upgrade/downgrade or a new generic import protocol.
Existing Windows HOLD conditions remain as defined by the Goal. Completing this
outlet alone does not close all Internal Beta data-safety/recovery requirements;
the stage's remaining executable protection and explicit recovery boundary stay
on the full product plan.

Start with a small actual counterexample showing the current CSV omits persisted
non-confirmed records and linked history/plans/relationships. Then exercise one
real user download containing these related records, including inactive states,
foreign currency and calendar evidence, plus an absent/corrupt/legacy original.
Prove that no surviving business records are silently omitted, another ledger is
not disclosed, secrets are excluded, files match the manifest, and export changes
no facts or client intents. Use actual PostgreSQL for snapshot/concurrency claims,
and temporary synthetic files for byte and failure paths. Run lengthy DB/device/
packaging qualification in the existing cloud lanes. No new proof framework.

The maintained atlas will record implementation and exact evidence as they arrive.
Preparation, this contract and a generated package schema are not completion.

## Implementation checkpoint, 2026-09-20

The candidate now supplies API and authenticated Web ZIP downloads through one
snapshot/archive owner. Its explicit collections retain authorized facts, states,
relations and history, with separately named account relationships. Derived
participant balances call the existing Debt query owner. Credential validation is
reused without activity writes or the global mutation fence; it is repeated after
packaging before download. The caller's transaction is not committed or rolled back.

JSONL keeps integer money and decimal FX precision. The manifest describes scope,
counts and content hashes. Original observations include current, cleanup and
accepted-receipt references; historical references never substitute the current
file or revive a known cleaned one. Identical captured bytes share a ZIP member.
Missing/corrupt/unverified originals remain explicit while surviving records export.
The ordinary budget is 2 GiB of uncompressed package content and five minutes,
with a 30-second SQL statement timeout. Exceeding it rejects the whole package;
there is no successful truncated result. Request-owned temporary files are cleaned
on success, failure and interrupted delivery.

Executed locally: 143 short tests including actual temporary original/ZIP bytes,
SQL authorization counterexamples, API/Web response lifetimes and existing Web
route inventory; Ruff and OpenAPI generation. Eight PostgreSQL/real-browser-session
tests were collected, not executed locally. PostgreSQL is still required to prove
the snapshot, independent-session interleaving and real authorized download.
This checkpoint is an implementation candidate, not main or Internal Beta RC.

## Current-head closeout

The first main-based CI exposed incomplete test fixtures: old import-template
contexts lacked the new export fields, and two real-database setup writers had
not acquired the existing currency write proof. Those inputs are corrected;
financial assertions and production write fences remain intact.

The three bounded review findings are fixed: cleanup references to the current
original retain its recorded digest; empty query results still check the shared
time budget; API/Web release their completed request read before the independent
export snapshot claims a connection. The reusable export service still does not
commit or roll back caller business work. Five new counterexamples failed before
the fixes; 45 targeted archive, pool-lifecycle, route and import-render tests now
pass, as does Ruff. Real PostgreSQL snapshot and download qualification remains
with the current candidate's cloud gate. A local PostgreSQL startup probe refused
an old test-runtime binary path, so it supplied no database execution evidence.

The next bounded review pass found two concrete export errors. Debt, repayment
and repayment-proposal receipts now inherit the parent relationship's actual
ledger/participant authorization. Historical original references share retained
deletion evidence only within the same expense identity and path, so replenishment
cannot revive a retired file through an earlier receipt. Three counterexamples
failed before these fixes; the 31 query/archive tests and Ruff pass afterward.
The preceding `e0cc4ff` candidate passed every PostgreSQL shard in CI; the revised
candidate still needs its own exact-head gate before merge.
