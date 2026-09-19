# Complete portable product data outlet

This delivery follows the active full-product Goal and the final 2026-08-26
Product contract §6.2–6.10, §7 and §18, within the post-G2 P1/P2 stage. Codex
has delegated product and implementation responsibility within those boundaries.
The existing product atlas remains the complete delivery plan. This document
defines the next portable-export task; it does not replace either architecture
contract or open Windows lifecycle actions.

Preparation starts from `6c4a8adf41f6c051ea288d64fda6e67550a0423e`, the isolated
original-integrity candidate. That candidate still requires cloud qualification,
protected merge and independent main qualification. Its verified original reader
is a dependency, not an already qualified new baseline.

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
