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

Mutation storage and transport are still to be selected from the existing command
and cleanup owners before dependent writes. Implementation must close all affected
consumers and retire replaced paths; a new read error alone is not this slice's
exit. Same-bill replenishment, explicit legacy verification and durable cleanup
remain part of the delivery, together with their actual client continuations.

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
