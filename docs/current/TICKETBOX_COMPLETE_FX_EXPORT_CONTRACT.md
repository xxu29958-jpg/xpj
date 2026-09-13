# Complete frozen FX evidence in confirmed CSV

Scope: the existing confirmed-bill export includes the frozen original/home
amounts, currencies, rate, rate date and source of refund, chargeback and reversal
facts. It reads the current fact snapshot; it never revalues or writes a fact.
Reversal retains the original purchase quote and contributes zero to the stream.
The legacy `exchange_rate_to_cny` column describes the exported original/home
currency pair; a non-CNY home currency is not relabelled as CNY.
This completes an existing RC outlet, not a revision archive or backup lifecycle.

## Impact closure before construction

| Boundary | Actual owner/consumer and required treatment |
| --- | --- |
| Stored fact and commands | `ExpenseOffsetFact` and `expense_offset_money` already freeze all evidence. Refund/date correction uses its applicable quote; reversal copies the root snapshot. No writer, schema migration or FX lookup is needed. |
| Query/projection | `expense_service._query` bulk-loads full same-ledger facts for both `list_confirmed` and `filtered_confirmed_stream`, then drops three FX fields in `ConfirmedOffsetStreamProjection`. Retain those nullable fields in this existing projection. |
| CSV success outlet | `stats_service.export_confirmed_csv` blanks the three existing FX columns for offsets. Fill them directly, preserve all column positions, integer magnitudes, signed contribution, filters and ordering. The “stream” is a financial event stream collected into `StringIO`, not HTTP chunked streaming. |
| API / Android | `GET /api/expenses/export.csv` uses authenticated ledger scope; `ExpenseLedgerRepositoryActions.exportConfirmedCsv` and `LedgerViewModel.exportCsv` share its returned bytes. Existing guarded binding, error and sharing behavior remain. |
| Web / Desktop / Owner | `GET /web/export.csv` resolves the Web/desktop session or visible local ledger; import/export page and Owner link use it. Viewer reading remains allowed. Desktop has no separate CSV writer. |
| Other projection consumers | API confirmed list and Web `web_app` / `_web_money_views` retain existing row meanings. Android `ConfirmedOffsetStreamDto` / `ConfirmedStreamMappers` read the established fields through ordinary Moshi adapters; added nullable metadata does not become an offline fact writer. |
| Other export formats | Reports API/Web CSV uses `reports_service.export_reports_overview_csv` aggregate sections, not this projection. Complete backup uses `backup_service` → `postgres_backup_adapter` / `pg_dump`, preserving database columns independently. Neither changes here; Windows lifecycle stays HOLD. |
| Import and recovery | CSV import treats rows as pending expense input through its existing owner; it is not a restore of offset lineage. This patch does not change import interpretation, command/OCC/receipt recovery or historical revisions. |
| Direct producers | New projection→CSV pure counterexamples; real command→API/Web downloads after replacing shared quotes. Existing `test_expense_confirmed_stream`, `test_expense_offset_fx`, `test_import_export_money_contract`, `test_viewer_write_guards`, and Web/Android confirmed-stream tests cover the retained semantics. |

## Verification and after closure

Before production changes, the actual projection→CSV producer failed for all
three offset kinds because its three FX cells were empty; the nullable legacy
case passed (3 failed, 1 passed). The API/Web PostgreSQL journey also checks
original amounts, zero-contribution reversal, ledger isolation and unchanged
fact bundles after reads; it awaits cloud execution.

After construction, the same ORM→stream→CSV owner chain retains all three
nullable fields; the offset-only blanking exit is retired. No extra query,
valuation, writer, command schema, database/cached fact or column order changed.
The paginated wire gains only optional nullable metadata. An Android Moshi
consumer test preserves the established list DTO while accepting those fields.

The first cloud candidate rejected redundant null/date branches in the existing
row formatter. CSV's native cell conversion and `safe_csv_cell` already cover them;
the branches are removed without a helper, suppression or changed blank-cell contract.
The four direct export cases still pass. The final complexity gate remains cloud-owned.

Bounded local verification: the four export cases pass; with the existing stream
envelope and exact-money parser cases, 10 tests pass. Ruff, OpenAPI snapshot check
and changed Android test's plain Detekt CLI pass. Plain Detekt does not prove
Android compilation or execution. PostgreSQL journey and Android tests await
exact-source cloud qualification. No device, lifecycle or full RC completion is
claimed. The product atlas retains overall delivery status.
