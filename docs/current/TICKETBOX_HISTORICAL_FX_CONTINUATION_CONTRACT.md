# Historical correction and missing FX continuation

## User outcome and owners

A user correcting a historical expense can resolve a missing exchange rate and
continue the same correction without losing input or changing its original
key, OCC, currency or date. The full Goal and final product contract remain the
authority. Existing Expense correction and manual-rate commands retain their
respective responsibilities; saving a rate does not itself correct the expense.

The correction owner checks OCC before applying money. On a missing-rate refusal,
the existing FX calculation has already determined the attempted source currency,
recorded home currency and effective rate date. Return those exact values in the
error details before rollback. Do not infer them from a later fact, device date,
current default or newly versioned correction payload.

## Impact closure before construction

| Boundary | Entries, consumers, original exits and direct proof |
|---|---|
| Expense and FX owners | Composite correction, shared claimed field mutation and confirm guard; missing FX returns exact context while fact/version/revision/claim roll back. Pending confirm consumers of the same guard retain their semantics. API/real-DB tests cover original retry after rate save and intervening OCC conflict |
| Error protocol | Existing `exchange_rate_pending` with additive `currency_code`, `home_currency_code`, `rate_date` details; Android error parser and correction dispatcher retain this context in existing `lastError`. No request protocol change, payload rewrite or new persistent column |
| Android original submission | Fact correction sheet/submission card, both global sync entries and outer/inner navigation graphs reach the existing rate editor. The failed original stays in Outbox; rate admission, dispatcher, receipt and OCC remain owned by the existing rate repository |
| Android recovery | Missing-rate context is a read projection of the failed original. Offer a useful rate action and explicit recheck; never automatically loop or substitute the latest expense token. Reopening and binding changes preserve/refuse the original correctly; Room/Route producers verify unchanged bytes/key/OCC and no advisor request |
| Native Web | Failed correction retains all raw scalar/item/split/reason/return fields and its original key/token. A distinct rate-save action reuses the existing rate service and returns to the same form. It does not submit the correction or replace its inputs. Native form/CSRF/role/OCC tests exercise both actions |
| Old success and dead ends | Retire loss of structured FX error context and the generic retry-only failure view. Do not add a guessed date/default, copied intent, second rate writer authority, automatic expense retry or advice-generation side effect |
| Other rate consumers | Budget, reports, overview, pending-expense FX and manual rate correction keep the same command/query owner. Reuse their actual rate/receipt contracts; leave unrelated rendering unchanged only after the call path proves it is independent |

## Construction and qualification

Write the direct missing-rate refusal and unchanged-original continuation
counterexamples first. Invalid or absent legacy context remains reviewable; an
unchanged retry may obtain current server refusal details, but no client guesses
missing money facts. A changed expense must produce an OCC conflict.

Web uses distinct native correction and rate-save actions while retaining the
original form. Android uses its existing Outbox and rate screen. Neither creates
a new queue, workflow state machine or currency authority. Keep physical-size
signals visible and review responsibility instead of mechanically splitting code.

After implementation, close the table against actual consumers and retire the
replaced exits. Qualification is bounded review, targeted local pure tests and
exact cloud/API/native/Room/Route evidence. No local long suite or Windows
lifecycle expansion. This closes one currency journey, not the full Goal or RC.

## Impact closure after construction

- The shared Expense confirmation guard supplies the attempted pair/date before
  rollback. Correction API, pending confirmation and Web command outcomes retain
  the same refusal code. ErrorResponse/OpenAPI declare the optional details;
  request compatibility and existing v1 correction payloads remain unchanged.
- Native Web saves rates through a distinct adapter to the existing FX command.
  A raw form projection preserves scalar and repeated child fields without
  diffing against a later expense. Rate conflict review changes only the rate's
  key/token. Both correction actions retain the original ledger before reads or
  writes; the shared retained-form template now round-trips repeated fields.
  Existing scalar-form consumers pass their direct retention tests unchanged.
  Unavailable original split members remain selected for explicit review; rate
  conflict review displays the actual current rate before a replacement. A Web
  correction requires its original key and OCC: missing values stay missing and
  are rejected before diff/claim. New GET and explicit conflict review remain
  the only preparations of new correction identities. The old POST-side UUID
  fallback is retired; direct producers obtain keys from the real form. The rate
  adapter is classified and checked as a writer route. Both confirmation and
  correction rejection tests use the canonical actionable missing-rate message
  while retaining their original no-mutation and rollback assertions.
- Android uses one validated missing-rate projection, one encoded failure context
  in existing Outbox, and the existing rate editor/command. Fact and both sync
  containers have real navigation entries. Budget/report validation reuses the
  same predicate; correction entry hides unrelated advice/month controls.
- Replaced exits are retired: discarded FX details, retry-only correction cards,
  rate-page navigation that loses the selected manual fact, and list-valued
  retained inputs serialized into one hidden string. Missing legacy details
  remain explicit recheck cases and never borrow a guessed date or currency.

Direct verification covers shared refusal/rollback, explicit continuation and
OCC conflict, native repeated fields and original tokens, Room restart/binding,
and actual navigation to/from the rate command. Local pure checks are bounded;
database, native browser and Android runtime qualification remain required.

Status: implemented candidate; bounded review closed, exact qualification open.
