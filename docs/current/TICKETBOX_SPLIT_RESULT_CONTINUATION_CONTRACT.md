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

## Impact before construction

| Responsibility | Actual consumer and required closure |
|---|---|
| Entrances | Relationships split center; source bill invitation card; receiver Web inbox and sender Web sent list |
| Facts/commands | Existing bill-split acceptance owns the invitation claim, received Expense, revision and applicable Debt in one transaction; no replacement owner |
| Queries | Receiver inbox is account-scoped; sent list is selected-ledger-scoped. Web already hydrates a receiver-authorized accepted result; API currently drops it |
| Currency | Backend freezes `home_currency_code`; Sent DTO reads it but mapper drops it, Inbox DTO omits it, both center rows format as CNY. Original submission recovery already uses frozen currency |
| Old success exits | Accept/reject/cancel only start another refresh. An acknowledged result can remain visually invited if that refresh fails. Accepted and sent rows lack fact continuation |
| Identity and role | Center retains lists/target choices without observing complete binding. Async reads/actions must capture the original binding; acceptance authority belongs to the chosen target's current membership |
| Persistence and protocol | Optional accepted-result projection needs no API epoch or migration. Keep Room rows, creation payload/key/OCC/receipt and server transition idempotency intact |
| Recovery | Query canonical accepted history after interruption/ACK loss; an inaccessible/archived target must not expose a usable fact reference. No background retry loop |
| Other containers | Web consumes the shared authorized result; Owner/Desktop/Shortcut do not own split acceptance or private ledger queries. Their financial/host writers are outside this unchanged command surface |

A receiver may follow its own received fact only while it has current access to
that ledger. Sender responses never disclose the receiver's ledger or received
fact. Receiver responses never disclose the sender's private fact/ledger. Reuse
existing membership queries; do not build per-page authorization rules.

## Direct verification and exit

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

After construction, replace stale statements above with final affected consumers
and retirement evidence. Qualification hashes/runs belong in the PR and external
evidence, not the product atlas. Whole Goal and Windows lifecycle HOLD remain.
