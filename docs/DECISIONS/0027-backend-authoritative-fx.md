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

## Amendment (2026-06-06) — transport, weekend fallback, manual trigger

**What changed.** Three additions; the data authority and snapshot semantics
above are unchanged.

1. **Transport: europa.eu XML → Frankfurter JSON** (`FX_RATE_SOURCE=frankfurter`,
   default). Frankfurter redistributes the *same* ECB daily reference set, so the
   data provenance stays ECB and rows keep `source='ecb'`. Only the host + wire
   format change. `FX_RATE_SOURCE=ecb` still fetches europa.eu directly.
2. **Weekend / holiday fallback.** ECB/Frankfurter publish on TARGET working days
   only. Rate resolution now uses the newest rate **on or before** the expense
   date (markets carry Friday's rate through the weekend) instead of an exact-date
   match. A tenant *manual* override stays exact-date. An expense predating every
   stored rate still resolves to `pending` (no fabricated rate).
3. **Manual trigger + visibility.** Owner Console `/owner/fx` shows sync status
   (source, last success, fail count, last error, latest rates) and a loopback-only
   "立即拉取" button. Scheduler and manual run share one code path
   (`run_fx_sync_once`) feeding one status snapshot.

**Why.** The daily sync silently went stale: europa.eu intermittently drops the
outbound TLS handshake from this host, the job ran only twice a day with no manual
retry, and weekend foreign expenses got stuck `pending` because the exact date had
no row. Frankfurter is key-free and reachable from mainland China without a proxy.
Domestic key-free sources were evaluated and rejected: 菜鸟汇率网 serves no JSON
API, mxnzp/聚合/中国银行牌价 now require an API key, and bank quote rates carry a
buy/sell spread unsuitable for mid-market bookkeeping conversion.

**Consequences.** No DB migration (source label unchanged). A single stale manual
rate can no longer shadow fresher global rates (manual is exact-date only). The
manual trigger does a synchronous ~1s network fetch — acceptable on a loopback
admin page.

**Verification.** `tests/test_fx_frankfurter_and_fallback.py` pins the JSON parse,
the Frankfurter dispatcher default, weekend resolution (Saturday expense → prior
Friday rate), pre-history still-pending, `run_fx_sync_once` counters on
success/network-drop, and the owner panel (403 remote / manual refresh renders).
`tests/test_fx_authoritative_contract.py` continues to guarantee no drift, no
fake 1:1, and pending-without-rate.
