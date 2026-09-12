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
The branch includes #402 integrated and independently qualified main 3503359d.
Final release qualification applies to the resulting exact candidate and main. No long local suite or full
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
replacement values supplied by the test.

Cloud RED: 1e289979 / CI34689080308 ordinary1 executed 4 actual native failures
(original OCC/key, cleared recovery, missing-OCC input loss), 2216 passed/3 skipped.
Its Android failure was an IO wait fixture error, not a business failure. Corrected
test-only 8b84af16 / CI34689821191 executed 2427 unit tests, with the one new
counterexample failing on different keys for the identical original target/body/OCC.
The load, first committed fact and unchanged-form assertions had passed.

## Impact closure after construction

| Path | Implemented result and direct proof |
|---|---|
| Android publication and recovery | DebtWriteRepository shares the existing Outbox lease/target/observation boundary for adjustment and repayment; original repayment payload is persisted before dispatch. DirectRepaymentIntentTest exercises actual owner/drain, refusal and retry |
| Android receipt and consumers | RecordDebtRepaymentDispatcher validates the exact receipt before atomic receipt/Done persistence. Detail plus all five retained query consumers and both Sync entries consume DebtWrite observations; DirectRepaymentRoomContinuityTest covers real Save, disk reopen, lost ACK and recovery |
| Android retirement/compatibility | Removed DebtActions.recordRepayment and the old direct success branch; replaced adjustment-only owner/surface with DebtWrite. Stored adjustment wire/payload remains readable; existing adjustment and member-owner tests retained |
| Web original submission | Native POST preserves original key/OCC/raw amount/date/timezone/binding through unknown outcomes and closed-debt recovery. Exact service ACK survives an independent detail-query failure; actual form tests retain the original controls |
| Web local continuation | repayment-entry uses the existing minimal draft store and Web Lock mechanism. Same-target originals block accidental replacement; explicit confirmed rejection can create a new draft. Existing Expense API/storage and six direct contracts retained; eight repayment browser-script contracts added |
| Web binding and result | Real authentication/binding test checks all five axes, no-write refusals and one receipt on identical retry. ACK clearing requires exact original values and receipt identity; no balance/history inference |
| Server/adjacent owners | record_repayment_idempotently remains the sole fact writer; no schema/migration/protocol version change. Member proposals, capture confirmation and their authorities remain separate; unrelated void/kind continuity stays in the product map |

Short checks pass: scoped Kotlin Detekt, changed Python Ruff, three template parses,
eight repayment plus six existing Expense browser-script contracts, and diff checks.
Bounded Android/Web production review found no remaining formal P1/P2; these checks
do not prove compilation or runtime. Exact candidate CI/CodeQL/Connected and isolated
VM Edge lost-response/reopen verification are pending. No merge or RC acceptance is
claimed; long suites stay cloud-only.

Candidate b15d91d4 exposed a real Web entrance failure in isolated Edge: Jinja
resolved the dict.values method instead of the original form values, leaving the
key empty and hiding repayment. Existing native PG and real-binding producers
also failed on those empty fields. Explicit item access fixes all form states;
short actual-template checks retain each original control. Cloud also identified
eight unmigrated Android test consumers and a positional-argument enqueue scan
miss; consumers and explicit typed publication were corrected without restoring
the retired writer or bypassing the audit. JS/Python command-result logic now has
separate small responsibilities (measured maximum CC11/9), with all14 browser-script
cases passing. The unchanged Desktop Node probe timed out once; its log is retained,
and the next exact candidate must independently pass. Final qualification is open.
