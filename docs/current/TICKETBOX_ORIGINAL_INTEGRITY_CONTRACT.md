# Original attachment integrity and continuation

This working contract implements the active full-product Goal and the final
Product contract §6.7, §7 and §18.7–8. The accepted product and post-G2 contracts
remain authoritative; this document records the delegated product choices and
impact closure for the next delivery. Starting source is `d42b9b2a4`, the isolated
calendar candidate based on main `44d684fb`; neither this preparation nor that
candidate is a qualified new main or a complete Internal Beta RC.

## User result and preserved capabilities

A person can tell whether a bill's linked original is present and matches its
recorded identity, view the correct bytes, and continue from a missing or damaged
file on the same bill. Financial amounts, accounting dates, relations, revision
history and original bill identity remain intact. A missing image does not block
ordinary financial reading, correction, export or planning.

Preserve authenticated and ledger-scoped API/Web downloads, existing HTTP file
semantics, legacy allowed paths, privacy sanitization on upload, upload ACK-loss
recovery, rebuildable thumbnails and their publication/cleanup protection,
intentional retention, orphan dry-run/grace and existing CSV event continuation.
Do not move existing files on startup or require a new installation, pairing or
import. The complete product data outlet remains the subsequent dependent work
in the product atlas; image checks or single-file downloads do not complete it.

## Meaning and decision rights

The current Goal delegates product and implementation decisions to Codex within
the established privacy, identity, financial and data-safety boundaries. These
decisions concern the existing attachment relationship; they do not authorize
writing daily data during construction or opening Windows lifecycle actions.

- The stored admitted evidence is the original this relationship identifies.
  Existing upload strips EXIF and normalizes image bytes before storing its
  digest. Keep that privacy behavior. Do not claim the stored file is an untouched
  copy of the camera input, or compare its digest with an unrelated raw upload.
- A manual bill with no linked original is valid. No reference, deliberately
  cleaned, physically missing, digest mismatch, and no recorded digest are
  different states. A derived thumbnail cannot prove the original still exists.
- A known digest is the expected identity. A missing or corrupt original can be
  replenished with the same admitted bytes under the same bill, through an
  explicit authorized command. A different digest cannot silently replace that
  original, create another bill or rewrite financial history. Preserve the
  attempted input and explain the mismatch so the person can select the original.
- A legacy file without a recorded digest remains readable as unverified evidence.
  Reading or scanning must not invent a historical digest. An explicit human
  verification may establish a current digest baseline with an audit of who
  verified which bytes; it must not claim a past capture or untouched source.
  A file changed since that review is a conflict, not implicit acceptance of the
  new file. An unavailable original cannot be recreated without a source copy.
- A verification result states what bytes and reference were checked, and when.
  It is an observation, not a second attachment authority. Avoid an independent
  inventory/cache or a mandatory full-store scan on every business page.
- Intentional cleanup must have durable authority before it irreversibly removes
  bytes. Failure or uncertain commit cannot leave an unexplained live reference;
  interrupted cleanup must remain retryable under its existing owner. Ordinary
  reads do not trigger financial or attachment mutations.

The status-quo path-only check contradicts the Product contract. Automatically
accepting replacement bytes or fabricating a digest contradicts provenance.
Removing image access or upload privacy would lose established capability.
Those are rejected as substitutes for this delivery.

## Owners, consumers and impact before implementation

| Existing boundary | Required continuation |
| --- | --- |
| Expense image reference/hash and ledger-scoped lookup | Retain the current relationship authority; metadata operations must use the real actor, ledger, OCC and existing idempotency mechanism. Financial fact revisions keep their separate meaning. |
| `file_service`, `expense_service._image`, stable file reader | One verified-read responsibility must cover identity, bytes actually consumed, bounded paths and cleanup of temporary resources. Verification followed by reopening a mutable path is insufficient. |
| API `/image`, Web media and their Android/Web consumers | Correct image or actionable state; preserve authenticated access, HEAD/range behavior where currently supported, and user recovery on the original bill. |
| OCR/re-recognition and thumbnail producers | Consume the intended original, preserve manual completion when recognition fails, and keep suggestions separate from confirmed facts. Existing derived-file success is not original health. |
| Data quality, bill details and Backstage | Explain the distinct states and provide the applicable check, replenishment or explicit legacy-verification action. Inspect large sets with bounded work and clear progress/freshness. |
| Upload staging, command receipts and offline callers | Retain original request/binding/key and stable accepted results; do not invent another queue or infer success from local acceptance. Follow every actual consumer before choosing the transport. |
| Cleanup and orphan handling | Retain retention policy, dry-run/grace and row/thumbnail concurrency boundaries; close the demonstrated durable-state/physical-delete gap without a new host lifecycle. |
| Original-copy/backup adapters and future portable outlet | Reuse existing stable-handle, digest and referenced-original work; preserve full-copy integrity. Keep current shipment exclusions explicit rather than reviving unrelated backup/restore actions. |

### Verified-read implementation decision

API/Web, real OCR providers and newly generated thumbnails will use one original
read owner above the existing ledger/path resolver and stable single-handle
reader. It captures and hashes the same bytes into a private temporary snapshot;
consumers use that snapshot and never reopen the mutable original after checking
it. The snapshot is request/work scoped and removed on completion or failure,
including interrupted HTTP delivery. It is not a persistent copy or inventory.
HTTP delivery continues through Starlette FileResponse, preserving its streaming,
single/multiple Range and invalid-range handling; HEAD is tested at the response
layer without claiming the current GET-only routes already accept HEAD.

Known SHA-256 identity mismatches stop original consumption with an actionable
integrity error. Legacy absent or unusable digest metadata remains readable but
unverified, retaining the old metadata until an explicit reviewed command; no
read creates or replaces a digest. Upload request and Android staging hashes
remain separate from the admitted original's hash. Existing thumbnails remain
usable derivatives, while actual original health is reported separately.

### Mutation and continuation decisions

The existing Expense row remains the relationship and concurrency owner. Add one
nullable, typed pending cleanup request there, with its reason/time and frozen
original/thumbnail references and per-file outcomes. Retain `image_deleted_at`
and `thumbnail_deleted_at` as completed cleanup markers; do not repurpose them
as uncommitted requests. This is smaller than expanding BackgroundTask admission,
dispatch and generic restart/cancel/retry semantics for each bill's bounded GC.
The existing cleanup owner must first commit the request, then re-lock and
continue that same request. An initial missing file is not intentional cleanup;
only an already accepted request can explain a missing file on retry. Counts
distinguish physical deletion in this run from settlement of earlier work.

Only one unresolved cleanup request is retained per Expense. Replenishment can
publish a new unique path while retaining the old frozen request; the old request
must neither delete the new path nor mark it as deleted. New cleanup admission
waits for the previous request to settle. A disabled policy stops new admission
and remaining deletion, retaining visible pending state. Explicit cancellation
first settles any already completed/uncertain deletion, then cancels only work
not executed. Metadata changes use existing row_version/updated_at and audit;
financial revisions do not acquire attachment or GC meanings. Completed history
can use the existing audit log; that log must not become a hidden execution queue.

Storage uses nullable `Expense.attachment_cleanup_request` (one validated JSONB
request, not arbitrary task payload) and `image_replenished_at`. Existing rows
receive no invented request or replenishment timestamp. A replenished original
starts a fresh configured retention period: compare the later of the relevant
confirmation/rejection time and replenishment time, so an old bill's restored
file is not immediately deleted again. Financial dates stay intact; merely
verifying legacy evidence does not renew retention. An existing frozen cleanup
request still refers only to its old files.

Replenishment and explicit legacy verification use the existing ledger writer,
actor revalidation, OCC and command-receipt owners. Accepted-key replay precedes
new execution checks and returns its original result. Replenishment admits exact
stored bytes unchanged when they match the known digest; a camera input may use
the existing privacy normalization before comparison. It must not blindly
re-encode an already admitted JPEG or reuse the Android screenshot preprocessor.
A different resulting digest cannot replace a known identity. Legacy verification
compares the explicitly reviewed observation with the current bytes and reference
before recording a new baseline and actor; a read never performs that adoption.
The verification command applies only to an absent/unusable recorded digest;
a known identity is checked through the read operation, never rebased by this
command. The reviewed digest and observed row version bind explicit verification.
Attachment writes use the existing installation metadata-write fence; original
reads remain available independently. Receipts describe accepted execution at
that time and do not substitute for a subsequent health observation.

Android will extend the existing UploadIntent/FileStore/Outbox target and receipt
branches for an existing expense, preserving its staged file, logical binding,
original key/body and OCC. Normal upload grouping and required enrichment receipt
remain specific to creation. A repair receipt resolves the same bill and media,
not a new Pending bill; it proves accepted execution, not permanent file health.
The Web native image form currently has neither durable file input nor a supplied
upload idempotency key. Reuse its existing logical draft/ACK owner with persistent
file accompaniment and migrate the affected image submit path; string-only manual
draft storage and a browser file input are insufficient. This is an explicit
missing capability to complete, not a capability removed from the product goal.

These decisions precede dependent storage and client writes. Implementation must
close all affected consumers and retire replaced paths; a new read error alone is
not this slice's exit. Same-bill replenishment, explicit legacy verification,
visible health and durable cleanup remain required with their client continuations.

## Evidence and exit

The initial executed counterexample on `19fd45a50` used a synthetic authorized
Expense and temporary files, then called the actual image resolver, route and
streamed FileResponse. Replaced bytes returned HTTP 200 despite a digest mismatch.
After physical removal, the API returned `image_not_found` while the actual Web
view still reported `available`. No database or daily attachment was accessed.
These attachment implementations are unchanged in `d42b9b2a4` and main `44d684fb`.

Start with small real-file counterexamples and existing route/upload/thumbnail/
cleanup tests. Prove correct and missing/corrupt/legacy/no-image paths, wrong
ledger/viewer denial for mutations, original-key replay, commit/ACK uncertainty,
concurrent cleanup/replenishment and unchanged financial facts. Use actual
PostgreSQL and affected client/packaging lanes on the final exact source for the
claims that need them; do not run ten-minute local suites or duplicate a proof
framework. Verify ordinary user task completion and retained file behavior before
closing this slice, then continue the same atlas toward the full product endpoint.

At `0d5854019`, verified snapshots and API/Web delivery are integrated with both
real OCR providers and thumbnail producers. The actual consumer RED had two OCR
mismatch failures and three missing thumbnail-identity interface failures, with
four matching/legacy controls passing. The integrated narrow run passed 68 tests
in 2.04 seconds, including Range, cancellation, legacy reads, correct snapshot
consumption and unavailable temporary storage distinguished from a missing original.
The existing upload/thumbnail/enrichment/cleanup group collected 67 tests; that is
collection only, not PostgreSQL execution. No daily data or installation changed.

`d6c9619d6` also carries three deliberately failing real-file cleanup tests:
after-confirm and both retention entry points remove bytes before their cleanup
commit is accepted. The confirmation case first commits the financial fact through
the actual command owner. Mock Sessions inject the cleanup commit failure; these
tests do not prove PostgreSQL persistence or concurrency. Cleanup, visible health,
same-bill mutations and client continuations are still incomplete. No source in
this preparation is a qualified new main or a completed original-attachment slice.

The next local checkpoint adds a ledger-scoped original observation route and an
explicit legacy verification command. Fifteen health tests cover actual temporary
bytes and authenticated HTTP reads; eleven verification tests use real temporary
files with command/OCC/receipt Session doubles. The latter establish application
ordering and metadata meaning, not PostgreSQL atomicity. The health/verification
group passed 26 tests in 1.26 seconds with `--noconftest`; the separate health/read
group passed 29 in 1.27 seconds. Consumer screens, replenishment, cleanup and
final exact-source database/client qualification remain open.

The backend continuation checkpoint includes a read-only per-bill health query
and four writer commands: verify a legacy digest, replenish the known original,
retry an accepted cleanup, and cancel its remaining work. Health includes pending
cleanup outcomes separately from the current original; an old request does not
make a replenished original missing. No response publishes internal references.
The required reviewed row version applies to all four commands, and the original
accepted receipt precedes fresh currency/OCC/file checks after current identity
revalidation. Binary replenishment uses the existing bounded multipart/raw reader,
with expected row version and original digest in query parameters. The existing
mutation audit now recognizes this required query carrier; no exemption was added.

Replenishment retains a usable existing thumbnail unless a frozen old request
owns it or it was already cleaned. In those cases the new source starts with no
current thumbnail reference and uses the existing regeneration owner; the old
request and its old files remain intact until that request settles. Newly saved
files are compensated only before a commit attempt; an uncertain commit preserves
the file for original-key reconciliation. `image_replenished_at` renews retention,
not financial history. The request schema is migration `20260920_0002`, with no
invented old request/date and a refusal to downgrade across retained evidence.

The local backend continuation group passed 115 pure/real-file tests in 2.48
seconds using `--noconftest`; four new real HTTP/PostgreSQL continuation cases were
collected only. Existing original read/OCR/HTTP tests and final integration are
rechecked against the combined checkpoint. These results do not qualify real DB
transactions, packaged execution, Web durable file drafts or Android continuation.
All remain required before this vertical slice is complete.

The combined backend checkpoint subsequently passed 192 pure/real-file tests in
3.63 seconds, including the pre-existing original HTTP/OCR/read contracts, command
continuation, durable cleanup and the query-token audit. Ruff and diff checks
passed; the generated OpenAPI contract records all five new endpoints. Four
PostgreSQL/HTTP cases remain collection-only locally and await the cloud lane.
