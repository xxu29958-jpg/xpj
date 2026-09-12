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

Test-only ba58c638 reproduced all three Web entry failures, the native PostgreSQL
foreign creation failure, and three actual Android route failures: currency choice,
record-payment entry and original-period return. Its fourth Android failure is the
parent's already-corrected missing error-message fixture. The parent foreign-bill
candidate is still under qualification. Minimum proof is scoped pure UI/form checks, real native
PostgreSQL flow, actual Android route execution, bounded review, exact candidate
cloud qualification and independent merged-main qualification. No local long suites.

## Impact after construction

Web and Android expose currency choice on creation; existing recorded units remain
unchanged. A legacy unknown unit pre-fills only the merchant and asks for the actual
currency and amount. Both clients reuse their manual Expense writer, preserve its
original command, and return to the captured obligation period. Web restores that
origin with its existing browser draft; Android retains safe navigation identity
and reads the durable Outbox creation receipt, since an Expense read cache can lose
its local client reference. No credentials enter navigation or draft context.

The central Web return adapter reaches the existing edit/FX/confirm/correction,
item/split/offset and missing-fact exits. Ignore and undo also return to the original
period using the existing lifecycle command and OCC. Android keeps the original
occurrence sheet across navigation and resumes its real query. An exact saved-bill
focus makes a later month's payment visible without changing its recorded date.
Only explicit occurrence association removes the reserve; recording, reviewing or
confirming a bill does not. Old hidden-currency creation and return-to-list exits
are retired; existing payment search and financial command recovery remain.

The direct native journey checks August's obligation paid in September, retained
invalid input, ignore/undo, FX review, explicit link and one counted expense. Short
Web/draft/return checks pass (37); changed Web function complexity excess remains
9 to 9. Android has six direct Connected producers and scoped static checks, but
new runtime qualification is still pending. Generated Web protocol fields are
optional navigation context; financial payloads and required API fields are unchanged.

The full product map retains shared accounting-time, complete exports, offline
reads/drafts, Backstage outcomes, consumer art and final RC delivery. This task
closes only the fixed-commitment payment journey.
