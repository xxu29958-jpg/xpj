# Stable accounting dates and original time intent

## Outcome and authority

A household can explain which day and month a financial event belongs to. The
same record, refund, budget, goal, report and export agree across clients and
display timezones. A date-only record stays date-only. Editing a note, retrying
an offline command or changing a calendar setting does not silently change the
original date, financial amounts or historical result.

This continues the full Goal and the [current product atlas](TICKETBOX_CURRENT_PRODUCT_ATLAS.md).
The governing semantic requirement is the final 2026-08-26 Product Rev 2.0
contract §10.2: distinguish `instant_utc`, `user_local_date`, `accounting_date`
and `calendar_revision`; do not hide DST, naive input or timezone changes in UI
conversion. The Goal delegates the in-bound product and engineering choices to
Codex. The latest user ruling requires preserving and strengthening capabilities.
ADR-0070 is historical guidance, not an additional authority or approval gate.
Its old Web offline limitation does not override the already implemented Web
draft, frozen command and ACK recovery capabilities.

Starting source is merged #422, `44d684fbbd49a4b35b8a386842c43e0c7e9e0445`,
tree `96e640ad7442b086b5b89b7a51d9407ef93ce320`. Its candidate qualified at
`a2eb2791`; independent main CI `35456525238`, CodeQL `35456525214` and Connected
`35456525210` all passed. That starting-source qualification does not qualify
the calendar implementation or mean that the whole product is complete.

## Decisions within the delegated boundary

### One ledger calendar and one financial date

The ledger owns an explicit IANA calendar zone and monotonically versioned
calendar rules. The initial choice and later changes are visible. Only an
authorized ledger owner changes the shared calendar; ordinary writers retain
their existing authority to record and explicitly correct financial events.
Changing the calendar applies to future interpretation, not a hidden historical
rewrite. Preserve the previous rules so a frozen command can identify them.

Reuse the existing time/spending and fact command owners. Persist the financial
event's accounting date and the calendar revision used to interpret it. A request
or device timezone may format a known instant but must not move an existing
record between financial periods. All confirmed-stream consumers read the same
stored date. Existing offset accounting dates are already facts and are preserved.
Recurring obligation periods remain distinct from the actual payment date.

An omitted current-period selection uses the ledger's current calendar, including
API, Web, Owner summaries and new plan forms. An explicit month or previously
captured intent stays unchanged. Display-zone preferences still format known
instants; they do not choose the default financial month or a record's day label.

Calendar choice is not an FX quote date or a currency-binding revision. Existing
original/home amounts, frozen quotes, source provenance and offset values must
not be recalculated during adoption or calendar changes. Explicit financial
corrections still use their current money/FX workflow and immutable history.

For a new quote, a known original user date is its transaction-date evidence;
legacy input uses its adopted date before any historical no-date fallback. A
change of accounting period alone does not request a new quote. Date-only
correction of the actual transaction date uses the existing FX recovery path.

### Preserve evidence; make legacy assumptions visible

Old root records generally preserve a UTC value, not the user's original date
or zone. Historical adoption freezes one explicit compatibility policy per
ledger, based on the default accounting view immediately before adoption. Record
the chosen zone, rule revision, adoption time and basis. A setting observed today
is evidence for this chosen compatibility policy, not proof of a historical
user's timezone.

Persist a legacy-assumed accounting date from the existing effective-time basis:
stored expense time, or the existing confirmation-time fallback where needed.
Retain the original values and identify which basis was used. Do not label a
confirmation time as a known purchase instant. Missing original user-local date
or source zone stays unknown. Do not rewrite old immutable revisions or receipts
to pretend these fields were known at the time.

Alembic expands the storage shape; it must not call application settings to guess
this policy. The installed maintenance path can run before the real runtime
settings are published. The correctly configured runtime passes its explicit
adoption snapshot to the calendar owner after identity seeding and before normal
workers/readiness. Include archived ledgers. Freeze a typed immutable rule row,
identified by ledger and revision, with the selected zone and adoption basis;
use existing ledger governance audit for its action/actor explanation. A restart
must resume the recorded policy, not choose again from new settings.

Adoption must preserve reads while currency adoption is still pending: existing
confirmed/month/CSV API paths can read historical periods in that state. Waiting
to fill accounting dates until currency adoption would make those periods empty.
Extend the existing database currency writer fence narrowly for this calendar
owner's metadata-only update. The database must verify that money, currency,
status, identity and all unrelated fields are unchanged. Do not fabricate a
CURRENT currency proof or permit ordinary financial writes through this path.

This one-time compatibility adoption does not increment financial fact revisions
or expense OCC versions, and does not fabricate a user correction. Its own rule
and governance evidence identify the adoption. Preserve the old offline commands
that depend on those versions. Existing projection refresh must nevertheless see
the calendar adoption: include its revision in the existing synchronization
freshness and preserve known time metadata when an old same-version receipt lacks
the new fields. Explicit user corrections continue to advance normal revisions.

The product shows the adopted policy, affected records and period differences,
and leads to the existing explicit fact-correction task for review. Assumed
history remains usable; requiring every old record to be manually approved before
ordinary work would regress the product. Missing usable date evidence or an
actual contradiction remains visible and recoverable at that record, without
inventing a date or dropping its financial value from an unqualified total.

For an adopted confirmed root with neither purchase nor confirmation time, the
existing all-record stream and CSV retain a nullable `stream_date`; offsets
continue to require their recorded day. Provide a ledger-scoped "账务日期待核对"
filter linked from the existing quality/calendar surfaces and reuse ordinary
fact correction. An audit timestamp may order the row, never supply its date.

Period projections expose `undated_expense_count`, counting matching confirmed
roots before a period restriction. While such rows can affect a financial
answer, totals, remaining balances, comparisons and achievement decisions must
remain unavailable rather than complete-looking zeroes. Known-date details may
still be shown with an explicit incomplete-data explanation. This is separate
from FX gaps. After an explicit correction supplies the date, the existing
refresh removes the gap and places the same fact in its chosen period. It does
not create a new expense, rewrite old receipts or require a second review owner.

A confirmed status, a known confirmation timestamp or an existing positive fact
revision each establishes that a root was published. A missing confirmation
timestamp does not demote such a root to an unpublished draft or disable its
ordinary correction command. If this legacy root has no revision yet, capture
its known pre-correction snapshot through the existing revision owner before
the correction. Do not invent a confirmation time; preserve the existing
permission, reason, OCC and original-key replay requirements.

It is impossible to preserve all former timezone-dependent period answers: the
current UTC and Shanghai answers already disagree. Preserve and explain one
compatibility baseline, the original evidence and the ability to correct it.
Keep display-timezone use for known instants; retire request-timezone authority
over financial period membership.

### New input preserves precision and the original choice

- Exact-time input retains the original local date, selected zone/offset and
  resolved UTC instant. An unchanged edit preserves that evidence. Capture the
  actual input zone when a draft is established, rather than substituting the
  device or server's later zone during send/retry.
- Date-only input carries an explicit precision and date. It does not acquire
  midnight, noon, the current time or confirmation time. The ordinary date-only
  form explicitly means a day in the ledger calendar. A source that gives only
  a different locality's date needs an explicit accounting-day interpretation;
  do not invent an instant to convert between zones.
- Handle nonexistent and ambiguous local times in the existing time owner.
  Preserve a nonexistent input for correction. An ambiguous input offers the
  two actual offsets; a known unchanged instant keeps its original offset.
  Neither case removes precise-time or date-editing capability.
- New commands freeze calendar identity/revision with the original intent.
  A later calendar change cannot regenerate their body. If current execution
  finds that recorded revision, it uses those frozen rules rather than forcing
  the intent onto the current revision. Unknown or contradictory evidence stays
  in the existing review/conflict task for explicit continuation.
- Native CSV's retained accounting date and raw event fields are evidence to
  carry through existing import review. Ordinary CSV, OCR and notification
  proposals retain their source precision and still require existing human
  confirmation. A suggestion does not become an independent financial writer.

### Existing commands, results and drafts survive

Authentication, original principal/ledger binding and key/body matching still
apply. A matched accepted command returns its saved success before new calendar
or current-OCC validation. New semantics must not invalidate an old successful
receipt. New response fields allow an absent historical value to mean unknown;
do not fill an old receipt from today's mutable fact.

Preserve absent/null/value distinctions and the old fingerprint field set.
Adding optional fields to a Python dataclass or client DTO must not append nulls
or today's revision to an old request. Keep Web v1 raw drafts, Android flat and
wrapped Room/outbox commands, original keys and ACK-before-clear behavior. A
note-only change must not opportunistically replace time evidence.

Old unaccepted input without source evidence uses an explicit versioned legacy
interpretation or retained review, never a silent current-device conversion.
If old raw input cannot reproduce a previously normalized request, recover its
original result through the scoped receipt/fact owner; do not bypass fingerprint
matching or issue a new financial command under a new key. Mixed-server support
uses existing capability negotiation and preserves the task when the new intent
cannot be represented. It must not silently strip the new meaning.

## Shared implementation shape

Use one optional `time_input` value on new Expense create/edit/correction requests.
It carries `precision` (`instant` or `date_only`), `calendar_revision`,
`user_local_date`, and the applicable `instant_utc`, `source_timezone`,
`source_utc_offset_seconds` and explicit `accounting_date`. Exact inputs validate
the original date and selected offset against the source zone. Without an
explicit accounting day, derive it once from the captured ledger calendar. An
explicit day is a user-selected interpretation; the existing correction command
still requires its reason. Date-only input never accepts an instant or offset;
an explicitly different source locality needs an explicit accounting day.

Omitted/null `time_input` supplies no new value object; it does not erase a saved
date. Legacy timestamp fields keep their original explicit-null meaning. An
unchanged legacy timestamp (including null on a date-only record) preserves
richer saved evidence. New date-only input is the way to keep a day without
claiming a clock time. The original field set still determines the request
fingerprint, including explicit nulls.

Persist Expense time evidence alongside the existing UTC `expense_time`:
`accounting_date`, `calendar_revision`, `user_local_date`, `time_precision`,
`source_timezone`, `source_utc_offset_seconds`, `accounting_date_basis`. Unknown
source precision is distinct from the legacy-assumed basis. Offset facts retain
their existing accounting day and date-only meaning. One optional
`accounting_time` response value presents this evidence; absent old receipt data
remains absent. The rule itself is resolved by ledger and revision, not copied
from a mutable display preference.

An imported file or accepted split can carry an agreed accounting day while
its original clock precision remains unknown. `recorded_date` preserves that
day without inventing a user-local date; confirmation must not replace it with
the confirmation day. Source rule identifiers are evidence, not authority in
another ledger. The receiving import batch captures its own valid rule before
review or deferred apply.

Legacy request bodies remain byte/shape compatible. Their accepted original
result wins; a genuinely new legacy execution uses the saved initial
compatibility rule and is explicitly identified as such. Known captured calendar
revisions remain usable for original offline intent even after the current rule
changes. New clients send the new value only under the existing server capability
contract. Do not scatter time fields or interpretation branches through each
writer; the shared time owner computes evidence and the existing financial owner
applies it in its current transaction.

## Impact closure and scope

| Responsibility | Required preservation and migration |
|---|---|
| Calendar binding | Existing Ledger management/bootstrap, owner permissions and audit; explicit initial rules/history and future-only changes, without a second settings authority. |
| Fact storage/history | Expense, confirmation/correction owners, immutable revision snapshots, existing offset facts; schema, historical adoption and revision evidence. Preserve money, identities, attachments and original snapshots. |
| Input owners | Manual create, pending edit/confirm, correction, OCR/notification proposals, split acceptance and native/ordinary CSV admission; no financial entry bypasses the shared interpretation. |
| Durable commands | Manual receipt, correction/idempotency, pending and recurring-payment commands; old JSON and exact fingerprints, original accepted result, OCC and transaction boundary. |
| Shared queries | Spending stream/month filters, FX projections, statistics/export, budget/goals, reports, recurring eligibility, search/rules/learning and recycle projections. Migrate actual date consumers; display and sort metadata must not masquerade as event time. |
| Web | Create/edit/correction forms, existing raw draft/ACK, confirmed day grouping/details/history, calendar governance, review/return navigation and export. Preserve native forms, permissions and input on errors. |
| Android | Picker/formatter, ExpenseDraft and mappers, DTO/Room/outbox and wrapped recurring-payment bodies, response/acceptedExpense decoding, facts/timeline/grouping; preserve offline creation, retries and original success. |
| Other surfaces | API/OpenAPI and runtime capability owner, Owner/ledger management; Shortcut upload remains the shortest capture path. Desktop does not gain a second financial or calendar writer. |
| Retirement | Remove dynamic query-zone period authority and date-only synthetic instants after consumers migrate. Do not remove valid timezone display, date editing, ordinary imports or drafts to satisfy old tests. |

Use isolated fixtures and cloud databases for implementation evidence and protect
the daily installation and data. Later installation actions follow the effective
user authorization; this document does not add an approval gate. Keep
Fresh-G2 CLOSED and the existing Windows lifecycle HOLD conditions; schema work
does not open complete backup/restore, upgrade or host mutation engineering.
Do not introduce a generic event engine, another outbox, or a proof framework.

## Direct proof and exit

Start with the actual shared owner: a CNY 100 purchase at
`2026-04-30T16:30:00Z`, adopted to May 1 under an explicitly recorded Shanghai
compatibility policy, and a May 1 refund. UTC and Shanghai clients must show the
same May financial result, including budget, goal, report and CSV consumers.
Retain the original instant and the fact that the original user date is unknown.

Use small local counterexamples for period stability, precise/date-only handling,
DST and legacy receipt/fingerprint decoding. Use the existing PostgreSQL and
client lanes for migration, actual HTTP/form/Room flows, calendar change with
offline intent, OCC/ACK recovery and currency/refund controls. A source-only or
pure-function result is not database or device evidence. No ten-minute local
suites or duplicated proof system.

Close the impact table against real entrypoints and consumers. Final candidate
qualification, bounded review, protected integration and independent main
qualification remain required. Then update the same product atlas and continue
the remaining portability, relationships, planning, continuity, visual and RC
work; this slice is not a substitute for that complete endpoint.

Initial RED on the starting production source: the existing pure
`stat_month_label` / `stat_time` owners produced **6 failing / 2 passing** probes
in **2.43 seconds**. A supplied frozen May accounting day still became April in
UTC/Los Angeles; date-only April input became May or acquired the confirmation
instant. The exact-instant control passed. The tests supply intended new fields
on in-memory Expense objects, so this proves the current pure owner does not yet
honor the contract; it does not prove database persistence, migration or UI
behavior. No production code or daily data changed for this RED.

Local implementation checkpoint (2026-09-20, source `df4be09d0`):
the kernel, adoption shape, original request/receipt preservation, shared date
queries, calendar governance, Web forms/drafts and Android data/forms/history
are integrated in the isolated branch. CSV captures its original input and
batch rule; split acceptance, offsets and OCR use the same evidence owners.
API, Web, Owner and Android default-month consumers use the ledger calendar;
explicit periods and stored draft intent win over a later default response.
Changing only the accounting day cannot fetch a quote or change the home amount.
Existing Web edits display and compare against the fact's same-ledger recorded
rule, so a merchant-only edit after a calendar change preserves unknown source
evidence. Explicit time, source-zone and accounting-day changes remain possible.

Confirmed legacy roots with no purchase or confirmation time remain in the
stream, CSV and cross-period missing-date task. One shared period projection
includes their scoped count; affected totals and comparisons are incomplete,
while unaffected categories remain usable. Web and Android explain the missing
date and retain the original root's correction path. Correction restores period
membership through the existing fact owner and preserves revision history.
No synthetic date, current clock, new receipt owner or independent cache is added.

At `58068e2ff`, the combined latest backend narrow run passed 70 tests in 4.36
seconds; all 25 Python structure counters remained within their existing
baseline, the service graph had no cycles and direct-head repository weight
reported NO DEBT REGRESSION. The later Web recorded-rule fix passed 57 targeted
tests, including the actual submit consumer and draft/ACK recovery. Integrated
Android source `56160bb1` passed 70 JVM tests, instrumentation compilation and
production/unit Detekt in 1 minute 24 seconds. Its Android tree is identical to
this checkpoint; no device execution is claimed by that local run. After both
final client fixes were integrated at `df4be09d0`, a combined Web time/form,
draft/ACK, correction and undated projection/revision run passed 70 tests in
4.05 seconds.

The first diagnostic cloud run belongs only to intermediate `b2268ac2`: CodeQL
and Connected passed, while CI exposed contract/fixture/old-schema integration
failures. Those findings are repaired in this checkpoint and await a new exact
head run. PostgreSQL migration/HTTP execution, full client qualification and
independent merge-main qualification have not passed for the integrated source.
The bounded adoption review found no current counterexample in transaction,
metadata-only writes, archived coverage or old-schema test boundaries; it was
source review, not attachment-byte or PostgreSQL runtime evidence. No candidate,
main or daily-installation completion is claimed.

Follow-up source `19986a856` incorporates the findings from cloud `19fd45a50`:
the two ordinary lanes had 12 fixture/projection expectation failures, and three
historical database shards had 9 old-schema seed/bootstrap failures. Existing
historical assertions and migration edges are retained; current bootstrap now
runs after those tests' existing upgrade to head and reuses the historical owner.
The two new protected calendar commands are recorded in the exact OCC inventory
(122 to 124 carriers, no new exemption). Android's two Compose resource-read
Lint errors are fixed through the existing stringResource pattern; submission
and validation meanings are unchanged.

The failed inventory lane now passes all 15 counters. The combined affected
Web/projection/inventory test selection passed 35 tests in 4.22 seconds; the
historical group collected 22 tests and retained its previous assertions and
48 migration calls. The identical final Android tree at `aba160f35` passed its
7 time-form tests, full Gray Lint and production/unit Detekt in 2 minutes 47
seconds. PostgreSQL rerun and complete final-source cloud qualification remain
pending; the passing CodeQL result on `19fd45a50` does not qualify this source.

The next diagnostic CI on `d42b9b2a4` passed both ordinary PostgreSQL lanes,
three historical database shards, contract/packaging and Android fast checks.
Its remaining real-db 1/4 failures were two historical bootstrap fixtures and
the existing unqualified FLOAT column's PostgreSQL DOUBLE PRECISION reflection
name. The fixtures now preserve their old-schema seeds and authenticate only
after their original head upgrade; the shape test normalizes only that exact
type alias and retains every other type, nullable, constraint and snapshot check.
The affected group collected 15 tests and its two pure shape tests passed.
CodeQL passed on `d42b9b2a4`; final-source CI/Connected and merge-main remain
required. These fixes change tests only, not financial or migration behavior.
