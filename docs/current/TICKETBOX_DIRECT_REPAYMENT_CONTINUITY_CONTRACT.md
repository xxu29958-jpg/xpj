# Record and recover the same direct repayment

## Product outcome and boundary

A household member records an external/manual debt repayment from Android or Web.
If the response is lost, restarting or returning to the original debt must recover
that submission and identify its one repayment receipt, including when it cleared
the debt. A changed balance alone cannot settle this particular command. Preserve
the original binding, debt, key, OCC, money and payment time before networking.

This is the next Relationships task in the full Goal, following financial read
propagation. Goal/latest rulings and the final Product contract sections 6.4/9
govern it. Development and isolated test changes, draft PR, qualification and
protected integration are authorized; daily-use data and unsent work are preserved.
The starting source is #402 candidate 2e97eeeb, not a qualified main. Final release
qualification must follow its actual integration. No long local suite or full
Windows lifecycle work; Fresh G2 remains CLOSED and lifecycle HOLDs unchanged.

## Impact closure before construction

| Path | Required consumer and retirement outcome |
|---|---|
| Android detail entries | Payables, receivables and debt-goal detail use the existing detail command boundary. Local publication, unknown result and exact acceptance remain distinct; keep original amount/currency/date and block accidental replacement commands |
| Android persistence/recovery | Converge adjustment and repayment on the existing debt submission/observation/recovery responsibility with two explicit command types, not two state machines. Preserve stored adjustment wire/payload and old rows; extend existing Outbox lease, binding, refusal, expiry, abandon and Sync consumers |
| Android API/receipt | Retire direct per-call new-key repayment writes. Carry explicit original paid_at and consume repayment_public_id from the existing response; canonical reads remain independent |
| Accepted-result consumers | Debt detail, debt/payables lists, receivables, debt-goal progress, create-goal candidates, repayment-capture candidates and activity history must consume the accepted change through their existing query owners; current #402 propagation remains applicable |
| Web native form | First submission, validation/conflict/unknown errors and success landing retain original key/OCC and date interpretation. Correct the old automatic-OCC-rebase success exit. Read failure after service commit is not a definite command refusal |
| Web persistence | Reuse the minimal binding/storage/immutable-submitted/Web-Lock mechanism from manual entry with a distinct repayment adapter. Keep Expense storage compatibility, drafts shelf and ACK behavior; native POST still works without JS |
| Web recovery entries | Reopen, refresh, BFCache and multiple tabs must preserve original context. Settled debts prohibit new repayment but can expose original-submission recovery. New binding cannot adopt old work; exact ACK controls clearing |
| Server fact owner | Reuse record_repayment_idempotently and its claim-before-OCC/atomic repayment receipt. Do not infer acceptance from a current fold or recent-history window; no second repayment writer |
| Adjacent commands | Member proposal/capture confirmation retain their own owners. Void, adjustment and classification may share detail guards; inventory and preserve their existing behavior, leaving unrelated continuity gaps in the full product map |

## Minimum proof and exit

First reproduce original retry/reopen failures through actual client boundaries.
Then qualify pre-network retention, ACK loss with exactly one fact, explicit payment
time, access/binding refusal, conflict versus unknown result, settled-debt recovery
and exact receipt. Exercise the real Android Room/Route and Web native/browser
producers; shared-mechanism changes retain existing manual Expense and adjustment
proof. Short local checks precede exact cloud gates and bounded review. Close the
after-impact table and physically remove replaced writers before integration.

Prepared counterexamples exercise the unchanged Android detail form through the
real repository after a committed response is lost; native Web recovery after a
committed read fails (partial and fully settled debt), changed default timezone,
missing OCC and stale OCC. Tests submit the returned form's actual controls, not
replacement values supplied by the test. Static checks passed; cloud RED and
production implementation remain open.
