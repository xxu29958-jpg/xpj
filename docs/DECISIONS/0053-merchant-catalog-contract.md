# ADR-0053: 商家目录与删除边界

- 状态：accepted target contract
- 关联：ENGINEERING_RULES §0 / §6 / §13、[[0038]]、[[0041]]、[[0042]]、[[0051]]、[[0052]]

## 背景

ADR-0052 split master-data deletion into smaller, safer contracts: monthly budgets are archived by configuration row, and custom categories are hidden through ledger-level preferences. The remaining gap is merchant cleanup: users can delete aliases, but there is still no true merchant master row to hide, restore, or merge.

Today the system has these separate concepts:

- `Expense.merchant` is a historical fact string from OCR, manual entry, CSV import, or notification drafts.
- `MerchantAlias` maps an alias key to a canonical display name for reports, stats, search, and rule matching.
- `RecurringItem.merchant_key`, debt draft merchant labels, CSV rows, and OCR facts are domain snapshots or configuration references, not a shared merchant row.
- Reports and lifestyle stats collapse enabled aliases at read time, but no stable merchant `public_id` exists.

External product/data references are non-binding calibration only. They show useful patterns such as human-readable merchant names, machine identifiers that should not be treated as immutable local facts, and the separation between display text and structured ids. This project still makes its own product decision: merchant catalog is a local ledger directory and display identity, not a rewrite of historical expense facts.

## 决策

**1. Merchant catalog is a ledger-level directory row, not a fact table**

If implemented, `merchant_catalog` represents current ledger merchant preferences and stable display identity. Recommended fields:

```text
public_id
tenant_id
display_name
merchant_key
status = active | hidden | merged
merged_into_public_id?
created_at
updated_at
row_version
deleted_at?
```

`merchant_key` uses the existing `normalize_merchant` rule and is unique within `(tenant_id, merchant_key)`. The first runtime slice must not add a hard FK from `Expense` to merchant catalog and must not backfill historical expenses with merchant ids.

**2. Materialization only affects current options and management surfaces**

Initial catalog rows may come from user-created merchants, confirmed expense merchants, or existing `MerchantAlias.canonical_merchant` values. Materializing a row does not change old expenses. Hiding or deleting a catalog row only affects merchant management, autocomplete/suggestions, and future configuration entry points.

**3. `MerchantAlias` remains the alias relationship layer**

The existing `MerchantAlias.alias_key -> canonical_key/display` contract remains valid. After catalog runtime support lands, alias canonical targets should either point at a catalog row or validate that the target key exists. During migration, keeping redundant `canonical_merchant` / `canonical_key` on aliases is acceptable to avoid breaking current stats and reports in one step.

Enabled aliases continue to drive:

- `/api/reports/overview` merchant ranking collapse.
- `/api/stats/lifestyle` frequent merchant collapse.
- Category rule preview / apply merchant matching.
- Web / Android search merchant normalization.

Deleting a catalog row is not the same as deleting aliases. If an enabled alias still targets that merchant key, catalog deletion must return `409 state_conflict` or a future `merchant_in_use`, requiring the user to handle aliases first or use a future merge flow.

**4. Hide, delete, and merge are distinct**

- Hide: remove from suggestions, default catalog lists, and new configuration entry points. Historical expenses and existing aliases are unchanged.
- Delete: soft-delete the catalog row and expose it in recycle bin. It must require `expected_row_version`.
- Merge: mark the source merchant as `merged`, point it to a target merchant, and optionally create a source-key alias to the target. By default it must not batch rewrite historical `Expense.merchant`.

The first runtime slice should implement only catalog list/create/patch/delete and unified recycle-bin restore integration. Merge/rename is a separate slice.

**5. Historical facts do not block deletion; active future producers do**

Historical `Expense.merchant` values do not block catalog deletion and are never rewritten by catalog restore.

Active configuration that would keep producing or normalizing to the merchant should block deletion, including:

- Enabled `MerchantAlias` canonical targets.
- Active or paused `RecurringItem.merchant_key`.
- Any future active configuration that explicitly binds `merchant_catalog.public_id` or `merchant_key`.

Debt repayment facts, bill-split snapshots, OCR facts, and CSV import rows are historical or pending facts; they do not block catalog deletion.

**6. Recycle bin contains catalog rows, never raw historical merchant strings**

Soft-deleted catalog rows can enter ordinary and owner recycle bins as `kind=merchant_catalog`. Restore follows ADR-0051:

- `viewer` can read but cannot restore.
- `owner/member` can restore.
- Restore checks row version and key conflicts.
- The explicit recycle-bin day-level retention window applies.

`Expense.merchant` strings must never become recycle-bin items. They are facts, not restorable entities.

**7. Candidate API shape for a future runtime slice**

Suggested catalog endpoints for a future implementation slice:

```http
GET    /api/merchants/catalog
POST   /api/merchants/catalog
PATCH  /api/merchants/catalog/{public_id}
DELETE /api/merchants/catalog/{public_id}
```

`GET` is available to `viewer`; writes are `owner/member` only. Mutating calls use `expected_row_version`; if routed through Android offline outbox, they must carry `Idempotency-Key` per ADR-0042. Before runtime implementation lands, these candidate endpoints must not be added to `docs/architecture/API.md` or the OpenAPI snapshot.

Restore should default to the unified `/api/recycle-bin/restore` path. A catalog-specific restore endpoint, if any, is a later implementation choice.

Future merge/rename must be defined later. Its invariants are: do not default to rewriting historical `Expense.merchant`, require OCC, require idempotency if exposed to offline replay, and require an explicit user choice about creating a source-key alias.

## 外部校准

These references are not dependencies, planned integrations, or product requirements; they only calibrate terminology and identity/display tradeoffs.

- Plaid Transactions: [`merchant_name`](https://plaid.com/docs/api/products/transactions/) is an enriched, human-readable counterparty name, and may be `null` when no meaningful merchant exists.
- Google Maps Platform: [Place IDs](https://developers.google.com/maps/documentation/javascript/place-id) can change over time and should be refreshed when cached for long periods.
- OpenStreetMap: [`brand:wikidata`](https://wiki.openstreetmap.org/wiki/Key%3Abrand%3Awikidata) separates a machine-readable brand identifier from the displayed `brand=*` text.
- Stripe: [statement descriptor guidance](https://docs.stripe.com/disputes/prevention/best-practices) emphasizes recognizable business names so users can identify charges.

## 后果

- Benefit: users can manage merchant directory entries without corrupting historical expenses.
- Benefit: alias-driven reporting keeps working while catalog identity is introduced gradually.
- Cost: old merchant strings still appear in historical expense details; that is correct because they are facts.
- Cost: merge/rename remains a separate, higher-risk flow that needs audit logs, idempotency, conflicts, and tri-surface UX.
- Rollback: if the first runtime slice only adds catalog rows and soft-delete endpoints, rollback can hide the UI/API while retaining the table. Do not bulk-clean `Expense.merchant` as a rollback strategy.

## 切片

1. This ADR: define merchant catalog, delete/restore, and merge boundaries; no runtime code changes.
2. Backend catalog table + API: list/create/patch/delete; block active alias/recurring references; integrate restore through the unified recycle bin.
3. Web / Android management surface: catalog list, hide/restore, and autocomplete filtering.
4. Merge/rename: separate ADR revision or follow-up ADR before implementation.
