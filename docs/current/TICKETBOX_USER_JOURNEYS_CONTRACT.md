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

A first-time Web budget writer starts with one total and one native Save in one
compact task region. Rollover, reserves, exclusions and category budgets remain
available under optional settings; configured budgets and rejected drafts expose
them immediately. The existing command, current month/ledger binding,
authorization and execution-versus-draft distinction remain intact. No wizard,
new financial default or second draft owner is implied.

Progressive enhancement closes first-use options only after installing the
validation-reveal handler. A browser-rejected input reopens its section and
receives native focus; without scripts every original input remains visible.
Durable refresh/session draft recovery is still a completion task. Evidence for
the compact form lives in the migrated qualification notes; current end-user and
visual acceptance remains in the atlas's Planning/Insights delivery package.

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
