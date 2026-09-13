# Split result continuation

Authority: current Goal and latest user rulings → final Gmail contracts → exact
implementation/runtime. This is one Relationships slice, not full RC completion.

## Goal and boundary

The household understands the frozen amount of a received or sent split, accepts
into its chosen writable ledger, and can follow the canonical result to the
existing financial fact. Acceptance stays successful when a later refresh fails.
Reopening the inbox recovers an accepted result from the server invitation.

Allowed: existing split query/DTOs, Android split center and repository adapters,
shared currency presentation, existing ledger switch/fact navigation, Web receipt
consumer, and their direct tests. Do not create another financial writer, queue
executor, state machine, exchange-rate authority or duplicate fact screen.

Acceptance remains an explicit online command. Its invitation ID and target ledger
already make canonical replay idempotent. The UI must not invent an offline enqueue
receipt or automatically retry a command against a newly selected identity/target.
The existing durable split-creation intent and its recovery remain unchanged.

## Impact closure after implementation

The test-first PR records the before-impact counterexamples. The current closure is:

| Responsibility | Consumer / retirement |
|---|---|
| Entrances | Relationships split center and source-fact cancellation capture the rendered binding; receiver Web inbox and sender Web sent retain their native entries |
| Facts/commands | Existing acceptance still owns invitation claim, received Expense, revision and applicable Debt atomically; no command or idempotency rewrite |
| Queries | `to_received_bill_reference` is shared by API and Web. Existing `list_ledgers_for_account` supplies current readable ledger names; API batches that membership read and Web reuses its existing map |
| Currency | Required frozen currency now reaches Inbox/Sent DTOs, domain models, both center lists and the source-fact sent panel; existing record currency formatting handles supported/unknown codes. CNY-only row formatting and ambient-currency dependence are retired |
| Command result | The same ViewModel adopts a canonical response before refreshing. Refresh failure retains its status/reference with separate feedback. Repeated taps cannot start another active command |
| Identity and role | Center reads/transitions and source-fact sent/cancel consume explicit complete bindings. Old callbacks without the rendered context are removed; replacement clears stale rows/targets and drops late results. Target membership still authorizes acceptance, independently of the current ledger role |
| Navigation | Existing ledger switch/fact route open the authorized received result; sent entries open their own source. Reference navigation supplies an optional exact-binding precondition inside the existing switch lock; ordinary serialized ledger selection retains its current behavior |
| Persistence/protocol | Optional `received_bill` adds no API epoch, migration or durable state. Room creation payload/key/OCC/receipts and server acceptance replay are unchanged; navigation tests compare the original failed row across a real ledger transition |
| Recovery | Account inbox reentry exposes the same canonical accepted record after ACK loss. Current disabled membership or archived target omits its reference; no automatic command retry or fabricated offline acceptance |
| Other containers | Owner/Desktop/Shortcut have no split-acceptance/private-result writer; Windows lifecycle remains held. Web receives the same authorized projection, without a parallel financial owner |

A receiver may follow its own received fact only while it has current access to
that ledger. Sender responses never disclose the receiver's ledger or received
fact. Receiver responses never disclose the sender's private fact/ledger. Reuse
existing membership queries; do not build per-page authorization rules.

## Direct verification and exit

- Protocol producer: generated OpenAPI matches runtime; Android pairs both the inbox
  and nested received-reference DTO, and no longer exempts frozen home currency.
- API: accept/replay and subsequent inbox read identify the same received fact;
  current viewer can read, disabled membership/archived target hide its reference,
  sender and unrelated account cannot obtain it. Existing atomicity/currency and
  party tests remain controlling for unchanged commands.
- Android: DTO → domain → real center renders JPY and supported/unknown currency
  through existing presentation; repeated tap issues one active command; canonical
  acknowledgement survives refresh failure; stale binding results do not publish.
- Actual navigation: receive → accept → authorized fact → back and sent → own fact;
  ledger selection uses the existing switch owner and does not relabel Room intent.
- Exact candidate CI/CodeQL/Connected, bounded review, isolated internal-device
  rehearsal as needed, protected merge and independent exact-main qualification.

CLOSED: candidate and merged main independently qualified; actual device navigation
and original-intent preservation verified. Evidence: [#391](https://github.com/xxu29958-jpg/xpj/pull/391).
Exact hashes/runs remain in the PR and external evidence. Whole Goal and Windows
lifecycle HOLD remain.
