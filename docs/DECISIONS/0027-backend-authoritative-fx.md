# 0027 Backend Authoritative FX

## Decision

The family ledger home currency is fixed to `CNY` for this phase. `amount_cents`
remains the home amount in CNY minor units for statistics, budgets, reports,
goals, CSV compatibility, and older clients.

Foreign-currency expenses store an immutable snapshot:

```text
original_currency_code
original_amount_minor
home_currency_code
amount_cents
exchange_rate_to_cny
exchange_rate_date
exchange_rate_source
fx_status
```

The backend is the only authority for FX conversion. Clients submit original
amount, original currency, spent time, and normal user-confirmed fields. They do
not call external FX providers, submit exchange rates, or calculate home
amounts.

ECB reference rates are fetched by the backend into `fx_rates` on a fixed
schedule. If the rate for the expense date is missing, the expense is returned
with `fx_status=pending` and no fake 1:1 conversion. Once a matching backend
rate exists, confirmation retries the backend resolver and freezes the home
amount snapshot. Already-resolved expenses do not drift when later rates refresh.

## Rationale

This keeps household accounting semantics stable: single expenses show the
original paid amount and frozen rate, while totals and reports stay in one home
currency. ECB is used as an official reference source suitable for bookkeeping,
not as real-time trading or payment settlement data.

## Compatibility

Legacy CNY-only clients that send `amount_cents` are treated as `CNY / base /
ready`. CSV import accepts older FX metadata columns, but imported expenses still
go through the backend FX resolver before a home amount is frozen.

## Non-Reversible Rules

Do not implement global currency switching as symbol replacement. Do not let any
client calculate foreign-to-home totals. Do not silently default missing foreign
rates to 1:1. Do not aggregate original amounts across currencies.
