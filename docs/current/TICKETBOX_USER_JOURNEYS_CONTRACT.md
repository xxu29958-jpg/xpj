# Ticketbox user journeys

These are the operative user journeys moved from the product atlas on 2026-09-07.
They derive from the Goal, latest user rulings and three final Gmail contracts;
they are not an independent product authority or a completion claim. The
[atlas](TICKETBOX_CURRENT_PRODUCT_ATLAS.md) owns capability status and remaining
delivery. [Historical qualification](../qualification/2026-09-07-product-atlas-history.md)
preserves the former evidence passages; later slice contracts own their evidence.

## Recognition and assisted entry

The Owner chooses manual entry, RapidOCR or local vision through one recognition
profile. The runtime settings owner validates and atomically publishes the safe
live configuration, making its effect visible without a restart. Receipt and
debt-bill consumers use the configured provider only when enabled. A usable
result supplies draft fields, confidence and provenance for explicit review;
unavailability or low confidence preserves the draft and provides retry or
manual continuation. Provider output never owns a confirmed financial fact.

Image preparation must retain the household and editing task that selected the
image. See the [debt-bill binding contract](TICKETBOX_DEBT_BILL_BINDING_CONTRACT.md).
Durable receipt intake and recovery are governed by the
[upload contract](TICKETBOX_UPLOAD_INTENT_CONTINUITY_CONTRACT.md).

## Currency adoption

1. An installation Owner opening a money page reaches the Desktop product
   bridge's adoption preview, including evidence and the binding revision.
2. The preview requires an explicit original home-currency choice, without a
   preselected environment default. The paired Desktop Owner confirms with the evidence token,
   OCC and idempotency identity.
3. The adoption service locks and revalidates the installation claim Account,
   evidence and binding, then records activation, durable receipt and audit
   actor. Only the canonical active binding restores money features.
4. Android reads the shared runtime compatibility conclusion before draining
   Outbox. Compatible immediate and queued writes carry negotiated API version
   and currency binding. Adoption-required status explains the installation
   Owner's next action; an unavailable negotiation or binding-activation race
   preserves the queued intent for later continuation.

The installation claim Account is the authority. A naked browser, another
Account or the retired maintenance API cannot adopt. Conflicting evidence leaves
every amount unchanged and leads to the existing Desktop diagnostics shortcut.
The browser form is a Desktop consumer, not a second adoption owner.

Fresh setup and an already implicit default binding also require complete user
paths. Persisted historical money meaning does not justify silently choosing and
locking currency. The [currency choice and correction contract](TICKETBOX_CURRENCY_CHOICE_CORRECTION_CONTRACT.md)
owns this remaining delivery; the completed legacy adoption slice does not prove it.

## Missing FX rate recovery

1. Pending review identifies the original currency/date and explains the block.
2. The existing Web and Android editors accept `1 original currency = N home
   currency`, explicitly for this bill only. A member may correct the rate before
   confirming.
3. The existing pending edit command saves the rate and edited amount/date in
   one Expense OCC/idempotency transaction. It records the manual source and
   effective transaction date, computes the home amount and returns a still
   pending bill. It does not change the shared daily ExchangeRate table.
4. The editor remains open for canonical conversion review before confirmation.
   Neither client supplies a competing financial calculator or treats an
   unreviewed local estimate as ready.
5. Android queues the rate in the existing PatchExpense intent while offline
   and explains that conversion awaits synchronization. Ordinary confirmation
   of an already-ready offline bill remains available.
6. Validation failure, conflict and response loss preserve the entire draft and
   original retry identity. Web/API use the same edit transaction owner; the old
   Web direct-commit bypass stays retired.

A ledger-wide manual daily-rate endpoint and one-bill recovery are different
tasks. Shared-rate administration and provider ingestion do not become effects
of editing a bill. Direct verification belongs to the real PostgreSQL edit
command, authenticated Web full/drawer forms and Android payload/queue/settlement
consumers, with schema and applicable exact-source cloud qualification.

## Manual expense entry

Web's native `/web/expenses/new` entry is reachable from the product shell,
overview, transactions and the `N` shortcut outside active editing. It reuses
`create_manual_expense`, records the actual Account/Device actor and retains
device-scoped `client_ref` replay. Confirmed creation and a missing-FX pending
bill remain distinct; the latter continues into the existing FX recovery editor.

The form carries its original ledger, browser Device public identity and create
identity. Refusal preserves entered fields and binding. Changing ledger refuses
instead of rewriting the destination; browser re-enrollment cannot turn an old
Device's retry into a new create. The shared command revalidates credential,
membership and role under the identity-lifecycle transaction lock. The shared
currency owner parses the amount, without imposing the home currency's browser
step constraint on foreign money.

The browser-local draft stores the six editable field strings, original create
key/phase and Dataset/generation/Account/ledger/Device scope, never credentials.
A Web Lock prevents another tab overwriting that draft. Unknown-response retry
retains the exact snapshot and key; only an actual saved manual Expense under
the current authenticated Device acknowledges retirement. Validation rejection
allows correction, while a changed binding cannot silently retarget the intent.
Old-Device drafts remain readable for manual reconciliation. Native/no-JS command
ownership remains intact. No full offline-browser startup or transparent
new-Device replay is promised.

The [consumer-art and convenience plan](../superpowers/plans/2026-09-05-consumer-art-convenience.md)
holds draft implementation and verification evidence. Real Edge persistence,
Web Locks and native form behavior complement the canonical PostgreSQL producer;
simulated persisted-page events do not establish physical BFCache admission or a
complete browser-process restart journey.

## External-debt context

An optional plain-text note, at most 500 characters, helps users distinguish
external obligations to the same person. It belongs to the Debt and shares its
authorized viewers; it does not change principal, repayment, settlement or
member consent. Web and Android carry it through the existing create command and
show it safely in canonical detail. Blank input becomes no note, and old rows do
not receive invented context. The former Web field that discarded input stays
retired.

This is create-time context, not an editable financial fact, chat or attachment
store. Later editing requires an explicit intent/OCC decision. Ordinary refusal
preserves the note. Submitted Android creation additionally keeps the original
payload, key and binding in Room before dispatch; local acceptance is not an
existing Debt. Recovery must identify the original record and offer retry or
explicit local-intent discard. Evidence belongs in the
[debt-context plan](../superpowers/plans/2026-09-05-debt-context.md) and the
[consumer-art and convenience plan](../superpowers/plans/2026-09-05-consumer-art-convenience.md).

## Budget first step

A first-time Web or Android budget writer starts with one total and one Save in one
compact task region. Rollover, reserves, exclusions and category budgets remain
available under optional settings; configured budgets and rejected drafts expose
them immediately. The existing command, current month/ledger binding,
authorization and execution-versus-draft distinction remain intact. No wizard,
new financial default or second draft owner is implied.

Progressive enhancement closes first-use options only after installing the
validation-reveal handler. A browser-rejected input reopens its section and
receives native focus; without scripts every original input remains visible.
Android retains the existing ViewModel draft and Room submission owners. Its
optional section belongs to the original month and full binding; configured
budgets and raw advanced input, including invalid input, stay visible. Original
currency, OCC, queue admission and both global recovery entries are unchanged.
The Route producer verifies total-only admission and acceptance, visible advanced
validation and month/binding isolation. Web durable refresh/session draft recovery
and exact Android runtime qualification remain completion tasks in the atlas.

## Planning query status and offline reading

A displayed query result, an original submitted command and a saved draft are
different things. Shared source labels must not promise offline storage merely
because a request completed or another operation is running. Empty first loads
and failed reads must not appear successful; existing result, error, permission
and original-submission feedback retain their own meanings.

The presentation change covers spending-goal list/detail/create, debt-goal
list/detail/create and budget advice. Shared Ledger, Inbox, Stats and Settings
callers retain their actual cache branches; expense detail/splits and recycle
retain explicit read-only feedback. No query, protocol, persistence or mutation
owner changes. Goal VM and Room recovery producers remain applicable; the old
blank-form/failed-read success labels and generic offline promise are retired.

Previously read Goal and Budget lists/details reopen through their durable query
owners; Recurring reading is also delivered in #444. They retain recorded
currencies and data time, with explicit access refusals handled separately.
Debt query persistence is merged in #446 after exact source CI, CodeQL and all
three actual native shards passed. Its corrected native journey retains real
navigation, Room reopening and offline access; the earlier missing-reentry
timeout is not business RED evidence. Neither page memory nor a
submitted-command receipt is a complete query snapshot. Offline reads do not
confer permission or prove current governance/tool health, nor promise that every
page works offline.

Income editing continuation is merged and main-qualified in #447. Same-identity role
changes retain the original raw input, currency, month and OCC; read-only access
blocks new writes without swallowing an in-flight original result. Android Back
or swipe retains the edit, while explicit Cancel discards it. Saved-state restore
uses the complete original binding and reconciles an already published exact
original with the existing Room submission owner, without creating a second
command. A changed identity hides the old form immediately; late restoration
cannot replace the current identity. Web write refusal returns the original form
and retry identity, preserving whether the user was saving or explicitly reviewing
new facts. Native saved-state registry restoration and actual Room recovery are
distinct from an OS process-kill qualification. Income creation is qualified
separately below; goal drafts, Web refresh/session draft durability and other
cross-client return paths retain their own status in the atlas.

## Spending goal creation continuity

Returning from a chosen future-month draft to the list and then reopening Create
must preserve the complete unsubmitted name, raw amount, category, currency and
chosen month. The list's currently displayed month is a default for a genuinely
new task, not authority to reset the existing task. Existing pending creations
remain discoverable through original-submission recovery; the Create entry must
not silently select the first unfinished command and replace an independent
draft. Explicitly inspecting an original and then returning to the draft must
preserve both original command identity and the unsubmitted input. Frozen source
`9eadd407` executed these counterexamples: CI `36362109478`, Android fast job
`108741221635` completed 2766 tests with exactly these two new failures at lines
114 and 138. Compilation or environment failure is not the claimed RED.

The qualified #451 implementation retains the creation owner at MAIN_ROUTE and restores its
complete binding, task key and raw input through the system saved-state registry.
A readonly role retains the current binding's draft and its Continue entry;
another binding never inherits it. Explicit original-submission inspection is
separate from that draft. A user-confirmed draft discard removes only the local
input, never stops a Room command or reverses an accepted target.

The existing Room creation transaction shared with income accepts a stable task key once and preserves its
immutable body and receipt. Two independent keys with identical content remain
two intended creations. An older system snapshot rejoins its own original key,
including a retained completion; unknown or abandoned originals remain evidence
instead of being filtered into an apparently new task. Their retained raw input
remains visible but cannot submit; the page distinguishes an unreadable status
or stopped original from a command waiting to sync. Publishing without a
recoverable original requires reconciliation or explicit local discard, never
automatic reinterpretation under the current month or currency. The existing
bare command payload, legacy explicit recovery and sole dispatcher stay in use.

Actual route destruction/reentry, registry save/restore and Room continuity are
separate checks; none is described as OS process-kill qualification. Final source
`f89a6d1d` and merged main `11352a29` independently passed CI, CodeQL and all
three actual Connected shards; main runs are `36381295871`, `36381295821` and
`36381295892`. Debt-goal drafts and Web refresh/session durability retain their
separate status in the full product map.

## Income creation continuity

Income creation must retain a distinct unsubmitted task across closing and real
route exit/reentry, including raw name/amount, source/frequency, original currency
and intended month. Closing is not an explicit discard. Same-binding role loss
must prevent submission while preserving the task; a replacement binding must
not receive the old intent. Once the existing Room owner accepts that creation,
continuation refers to the original key/body and receipt instead of creating a
second command. Two deliberately separate plans with identical fields remain
two creations; body equality is not task identity. Frozen source `d59498cf`
executed the actual pop/reentry and failed on the restored name being empty
(Connected `36359132642`, native job `108732697844`, line 155). The qualified #450 implementation
moves creation input out of the route-owned listing into the existing outer
MAIN_ROUTE and SavedState mechanism. Stable-key acceptance is atomic in the
original Room owner, including retained completed submissions. An older system
snapshot first rejoins the matching original key and complete binding even if
the accepted input is newer; it must not resubmit the old input. An unresolved
publication keeps raw input and offers original-submission recovery. Current
runtime qualification passed on final source `4c9a3618` and independently on
merged main `021ea137`: CI `36376782029`, CodeQL `36376782049` and Connected
`36376782067`, including all three actual native shards. This does not claim OS
kill qualification or completion of other goal and Web draft journeys.

Creation admission errors remain attached to the same raw draft through reopening and
system saved-state restoration. An unknown or abandoned original row must not retire
the input into a list that cannot display it. If the original submission can no longer
be found, the user can explicitly confirm discarding only the local draft; this does
not cancel a server-accepted income or automatically submit another plan. The income
creation form opens fully expanded so its retained month and currency are reachable
without first expanding a partially visible form. These behaviors are included in
the qualified #450 source and main above.

## Unused tag cleanup

The Library tag page offers all/unused views within the selected ledger. The
unused view hides used rows but keeps every live same-ledger merge destination.
Rename, merge, delete, validation recovery and undo retain the selected view;
readonly viewers can inspect it without acquiring write authority.

Rename, merge and delete from the unused view reuse their existing commands and
require that the source tag is still unused when accepted. The merge target may
already be used. A stale page must not remove a tag reused by a financial writer,
rewrite that new bill, or hide its live tag. Normal explicit tag deletion keeps
its existing affected-bill behavior, as do rename and merge from the all view.
Refusal is visible as an error; original OCC,
actor, ledger isolation and undo identity remain owned by the existing services.
The duplicate Owner cleanup page, handler and navigation retire only with this
capability present in the Web consumer. Exact candidate status stays in the atlas.

## Recycle recovery

Owner Console enters the canonical Web business recycle journey with the actual
business session and ledger permissions. Its duplicate query/restore surface is
retired. Every restored entity keeps its existing command owner, including OCC;
ledger governance restore remains on the Owner ledger page.

## Household invitation

The invitation carries the task: preview the household ledger and role, then
accept as an existing identity or supply only a display name. Device identity is
product-owned. Authorizing another device uses the existing session/enrollment
owners. After verifying identity and ledger, a writer can capture or enter a
bill; a viewer can read recent transactions. Failure recovery stays in that task.

The shared invitation result may supply
`https://configured-origin/web/auth/join#invite=...`; its origin comes from the
configured public endpoint, never the request Host. Without that configuration,
the one-time token remains available for explicit paste. Configuration does not
prove reachability, and this introduces no token store.

Web removes the fragment before native preview submission. Each acceptance form
retains its own target instead of a shared target cookie. Existing identity is
checked independently of the old selected ledger while preserving Web platform
and expiry requirements. New browsers reuse recoverable enrollment proof and
the browser-pairing eight-hour policy.

The confirmation also retains the Account public identity shown in the preview.
A different login in another tab refuses before invitation consumption and
presents the new identity for explicit confirmation. Anonymous previews are
explicitly unbound; two anonymous invitations may establish and reuse one
browser identity through existing enrollment/replay. The public form marker
compares stale intent; it does not authenticate or grant membership.

Android accepts paste or explicit text sharing, previews anonymously, and
compares server identity and data generation. Same-server acceptance uses the
current authenticated binding. A foreign server opens browser continuation and
cannot receive the stored credential or replace app identity/Outbox. Arbitrary
domain verified Android App Links are not promised. Real session/form and
enrollment producers, Edge fragment handling and Android transport/session/Outbox
consumers own the direct verification of these boundaries.

## Local Web identity

Loopback location is not identity. On an installed dataset the browser consumes
the single `InstallationOwnerClaim.account_id`, shows the real Account and live
ledger/role choices, and establishes a recoverable eight-hour Web Device/session
after explicit confirmation. The claim's Windows source Device must still be
live and owned by that Account. No technical code, device name, prior Desktop
launch, first-Account guess or anonymous Owner grant replaces this check.
Development datasets without a claim keep their explicit development-only path;
missing or ambiguous installed claims enter recovery instead of choosing an
identity.

A session principal is independent of its compatibility-default ledger. A live
Account/Device can choose another active membership without changing identity.
Every read/write reuses current role and ledger state. Revoked membership or an
archived ledger cannot be restored by a cookie. Invalid, expired or revoked
cookies are cleared and return to the identity task. Recovery drops a stale
`ledger_id`; expired unsafe submissions return via the same-origin Web GET page,
or `/web` when no safe referrer exists, not a GET of the mutation URL.

An otherwise valid cookie for another Account is also cleared on installed
loopback. Local logout revokes the browser token and returns to confirmation;
public logout retains pairing entry. Confirmation and a proven lost-response
retry reuse enrollment proof, Device and token. Reusing proof for another Account
or ledger refuses and clears that spent proof so a new confirmation can recover.

Owner device inventory derives browser availability from live, unexpired and
unrevoked Web credentials. Ended sessions remain collapsed history and do not
count as connected devices. Reconnection creates a separately accountable
browser Device. Counting/listing does not revoke or remove another session or
historical Device. The public Device API keeps its revocation meaning.

Real PostgreSQL browser forms and stored actor/Device checks prove issuance and
financial attribution; live-role/archive, invalid-cookie, ledger-switch and
same-proof replay/refusal cases exercise their direct producers. Public pairing
and Desktop bridge regressions remain relevant consumers. These checks confer no
installer or restore qualification. Desktop original-code continuation has its
own [first-use contract](TICKETBOX_DESKTOP_FIRST_USE_CONTRACT.md); a complete
ordinary household entry rehearsal is still required.

## Restore-dependent identity HOLDs

These remain visible limitations, with reactivation through the held restore
qualification or an independently scoped, authorized identity change:

- Local Web GET preview does not bind its expected Account/dataset generation
  before the first POST. A restore that replaces identity while retaining a
  selected ledger can issue a replacement-identity session. The future fix must
  carry expected identity in confirmation proof and compare it under issuance
  lock. Direct owners: `web_auth.local_web_identity_form`,
  `local_web_identity_submit`, and
  `identity_service._local_web.connect_installation_web_identity`.
- Unbound Android invitation enrollment does not persist the preview's dataset
  generation. Restoring the same unused invitation between preview and acceptance
  can admit a changed generation. The future fix needs expected identity in the
  durable enrollment intent/secure codec and validation before publication,
  including process recovery; a ViewModel-only check is insufficient. Direct
  owners: `dataset_restore_service.resolve_restored_dataset_plan`,
  `DeviceEnrollmentIntent.Invitation`, `SecureDeviceEnrollmentCodec`, and
  `DeviceEnrollmentCoordinator.accept`.

Neither finding opens Windows lifecycle work or blocks an unrelated current
consumer slice by itself. The historical review subjects remain in the evidence
archive. Fresh G2 stays CLOSED and the Goal's Windows HOLD boundary is unchanged.

## Saved financial views (#449 merged)

Under the Goal's delegated product-design scope and product contract 6.9, saved
views are named, ledger-shared query configurations. The UI states this sharing
scope before saving. Current Owner/Member authority permits management; Viewer
may read but receives no new write command. A view does not grant access to its
ledger, and every operation rechecks current identity, membership and ledger
state through the existing Web/session boundary.

The first consumer is the confirmed financial stream, discoverable from Library.
Save, reopen, rename and delete reuse its existing query semantics. The saved
conditions include an explicitly fixed accounting month or the ledger's current
month, the existing cross-period health filter, stable tag identity and an
explicit presentation currency. Cross-period health filters do not acquire a
hidden month restriction. Presentation currency never reinterprets original
amounts or historical accounting dates; missing FX remains explicitly incomplete.

Reopening executes the original query against current authorized facts. It does
not freeze result IDs, amounts, rates, pagination, bulk selections or command
keys. Tag rename follows the same identity. Deleted, merged or missing tag
references require visible repair instead of dropping the condition or silently
following a broader replacement; same-identity undo may restore the reference.
Names cannot silently overwrite another view. Original retry identity, actor,
OCC conflicts and the existing complete portable outlet are part of delivery.

The frozen `38175eb` browser journey ran against PostgreSQL and failed because
the confirmed stream had no save entry (CI 36354760118, job 108720371992).
The implementation adds one SavedView persistence/query owner, its schema migration,
native confirmed/Library forms and the existing portable outlet. Invalid or
refused forms retain original inputs and key/OCC; switching the current ledger
cannot retarget an old form. An unavailable tag remains selected until explicitly
repaired. The shared product shell covers both desktop and narrow Web navigation.

Direct regressions cover current/fixed months, new facts after reopening,
cross-ledger and revoked membership, Viewer write refusal/recovery, stable retry
receipts after rename/delete, OCC and name conflicts, real tag rename/merge,
schema preservation and export scope. Final source `f61bb93d` and merged main
`609448a9` independently passed CI, CodeQL and all three actual Android Connected
shards. This does not claim a daily installation update, replace the full Goal or
reopen Windows lifecycle work.

## Debt-goal creation continuity

A debt-repayment goal retains its nonmonetary definition: name and selected debt
identities, without inventing a target amount, currency or spending month. One
original creation key must resolve to the same goal after a real repayment has
changed its linked debt. Retrying that task must neither create another goal or
link set nor record another repayment. Reusing the key with a different name or
selected debt set must be refused without altering the accepted original.

Frozen source `1788f1b3` executed three business failures in CI `36376017160`,
job `108781938777`: the API bypassed Web's existing idempotent service, retry
created another goal and changed name/selection each returned success; that job
also passed 2757 other cases. The candidate API now shares that service and
atomically stores the original creation receipt with its goal/link rows. A
retry returns that receipt after real repayments or target-date changes, while
ordinary GET returns current facts. Legacy keyless clients retain nonmonetary
creation. Historical Web redirects may still locate their accepted goal;
an API original with no frozen receipt requires review rather than inventing
the initial result from current facts.

Android's unsubmitted name/selection reset executed at frozen source `ecfe2aca`:
CI `36379287818`, Android fast `108791533108` ran 2804 tests with only the new
`returningToCreationRetainsRawNameAndSelectionForExplicitReview` failing. The candidate moves debt-goal
creation from the Reports direct writer into the existing Goal command owner,
Room acceptance and dispatcher. MAIN_ROUTE/system SavedState retain the raw
name, selected debt identities, complete binding and stable task key. Inspecting
another original cannot consume that independent draft. Candidate refresh keeps
unavailable selections visible for explicit removal instead of silently dropping
or replacing them. Readonly users can inspect retained input and stop an eligible
local original; retry still requires write authority. Unknown or stopped
originals retain evidence without becoming new submissions.

If a system snapshot predates the fields actually accepted by Room, the form
shows the accepted name/selection under that original key; it cannot substitute
the older inputs or issue a second creation. Matching raw input is retained.

Global recovery carries the original's goal type and opens the debt form with
its original name and selected debts, without money or month fields. The old
Reports creation writer is retired with its direct consumers migrated. Native
route destruction/reentry, system registry restoration over reopened Room,
ACK-loss/receipt continuity and same-key concurrent acceptance have dedicated
candidate regressions; runtime and exact source/main qualification remain
pending. They do not claim an OS kill, replace the existing goal lifecycle or
declare the whole planning domain complete.
