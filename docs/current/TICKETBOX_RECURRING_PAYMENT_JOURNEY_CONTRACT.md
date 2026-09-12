# Fixed commitments through actual payment

## User outcome

A household can express a fixed commitment in its actual currency, understand
the reference valuation used in its budget, record a missing payment, and return
to the original obligation month to associate that confirmed bill. Saving a plan
or a payment does not declare the obligation fulfilled. Only the existing explicit
occurrence link removes its outstanding reserve; unlink/reversal retain their
current semantics.

Goal/latest rulings and final product contract govern this work. Reuse existing
RecurringItem, occurrence, Expense, valuation, browser draft and Android Outbox
owners. No new financial writer, matching engine, protocol state or Windows scope.

## Impact before construction

| Boundary | Actual entries, consumers and required closure |
|---|---|
| Fixed commitment creation | Web recurring create form and Android editor must expose currency choice and use that currency's minor units. Existing records and observed candidates retain their recorded basis; creation must not reinterpret another currency as the current household default |
| Planning reads | Recurring list, occurrence period, budget inputs/month/advice and reference-rate metadata already have distinct original and valuation responsibilities. Verify foreign planned amount, actual publication date and missing valuation without inventing a paid fact |
| Record payment | The original Web occurrence page and Android occurrence sheet open existing manual Expense entry with merchant/currency/amount suggestions. Actual payment date remains editable. Server/client original series lookup supplies the suggestion; navigation context grants no write authority |
| Return and association | Carry original ledger, recurring public identity and period through manual draft, accepted creation, pending FX review, confirmation and fact viewing. Return to the original period, refresh its real query and explicitly choose the confirmed payment, including payments recorded in another month |
| Draft, protocol and recovery | Preserve original manual create key, binding and raw fields through refusal and ACK loss. Add navigation context to existing draft storage with compatible reads of older drafts; do not retarget an old financial intention on ledger/device change. Retain occurrence OCC, original key and dispatcher recovery |
| Shared expense consumers | Web ExpenseReturnContext is consumed by full/drawer edit, FX, lifecycle, correction, items, split, offset and fact-return links. Android shell/manual/edit/fact routes must preserve the caller's period and refresh on return. Existing list/report/search origins must still work |
| Old exits | Retire create-time currency locking and the instruction to leave the period, independently find manual entry and reconstruct the original association context. Keep existing search/association for previously recorded payments |
| Direct proof | Native Web forms and actual MainNavGraph tests start from the plan entry, exercise foreign units and preserved period, then verify a confirmed link changes only the applicable reserve. Existing permission/OCC/receipt/reversal tests remain direct financial-owner producers |

## Gate and current state

Three actual Web entry counterexamples failed against 6de1bb39: the create form
has only a hidden currency, the unpaid period has no payment-entry action, and
the expense return adapter drops the original series/period. Native PostgreSQL
and three actual Android navigation producers are prepared; cloud execution is
pending. The parent
foreign-bill candidate is still under qualification; this isolated work does not
change that candidate. Minimum proof is scoped pure UI/form checks, real native
PostgreSQL flow, actual Android route execution, bounded review, exact candidate
cloud qualification and independent merged-main qualification. No local long suites.

The full product map retains shared accounting-time, complete exports, offline
reads/drafts, Backstage outcomes, consumer art and final RC delivery. This task
closes only the fixed-commitment payment journey.
