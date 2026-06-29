package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * ADR-0049 §2 (slice 8) — Android contract for the Debt entity surface.
 *
 * Mirrors backend `DebtResponse` / `DebtListResponse` / `DebtCreateRequest` in the committed
 * OpenAPI snapshot (gated by `OpenApiContractGateTest`). Money is home-currency minor units
 * (cents). `remaining`/`paid`/`status` are server-derived from the append-only fact fold —
 * never an editable local truth.
 *
 * `ledgerId` is NULLABLE: the backend redacts it to null for a cross-ledger participant view
 * (§5.2). Use [publicId] (+ [counterpartyAccountId]) as the local key, never `ledgerId`.
 */
data class DebtDto(
    @param:Json(name = "public_id")
    val publicId: String,
    // Redacted to null for a cross-ledger participant; do NOT use as a local key.
    @param:Json(name = "ledger_id")
    val ledgerId: String? = null,
    // i_owe / owed_to_me (owner-account relative; see DebtDirections).
    val direction: String,
    // member / external (see DebtCounterpartyTypes).
    @param:Json(name = "counterparty_type")
    val counterpartyType: String,
    @param:Json(name = "counterparty_account_id")
    val counterpartyAccountId: Long? = null,
    @param:Json(name = "counterparty_label")
    val counterpartyLabel: String? = null,
    @param:Json(name = "principal_amount_cents")
    val principalAmountCents: Long,
    @param:Json(name = "remaining_amount_cents")
    val remainingAmountCents: Long,
    @param:Json(name = "paid_amount_cents")
    val paidAmountCents: Long,
    // open / cleared / voided (derived fold, ADR-0049 §2; see DebtLinkStatuses).
    val status: String,
    // manual / bill_split (see DebtSourceTypes).
    @param:Json(name = "source_type")
    val sourceType: String,
    @param:Json(name = "source_id")
    val sourceId: String? = null,
    // 8e-6e external-debt repayment-rhythm classification (unspecified/revolving/installment/one_off;
    // see DebtKinds). DEFAULTED — DebtResponse.debt_kind is defaulted (not `required`), so an older
    // payload that omits it decodes to "unspecified" and the contract gate's reverse check is silent.
    @param:Json(name = "debt_kind")
    val debtKind: String = "unspecified",
    // §B 完整 installment 合约排期（仅 installment 外部债非空，其余 kind 为 null）。count/period 是
    // at-rest 排期；payoff_date 与 paid_count 是后端 DERIVED 只读派生（建账+期数×周期 / floor(已还/每期)）。
    // 全部 DEFAULTED — DebtResponse 把它们设默认（非 `required`），故旧 payload 省略它们时解码为 null、
    // 契约门反向检查静默；它们是已声明属性 → 正向检查通过（[[project_android_openapi_contract_gate]]）。
    @param:Json(name = "installment_count")
    val installmentCount: Long? = null,
    @param:Json(name = "installment_period_months")
    val installmentPeriodMonths: Long? = null,
    // ISO date 串（后端 `date` → "2027-06-20"）；UI 按月粒度呈现（parsePayoffYearMonth）。
    @param:Json(name = "installment_payoff_date")
    val installmentPayoffDate: String? = null,
    @param:Json(name = "installment_paid_count")
    val installmentPaidCount: Long? = null,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
    @param:Json(name = "original_currency_code")
    val originalCurrencyCode: String? = null,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long? = null,
    // Decimal serialized as a string by the backend ([[0027]] snapshot provenance).
    @param:Json(name = "exchange_rate_to_cny")
    val exchangeRateToCny: String? = null,
    @param:Json(name = "exchange_rate_date")
    val exchangeRateDate: String? = null,
    @param:Json(name = "exchange_rate_source")
    val exchangeRateSource: String? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "row_version")
    val rowVersion: Long,
    // ADR-0049 §3.2 (slice 8d): server-authoritative viewer role for a member Debt (true=debtor /
    // false=creditor / null=external·not-a-party·non-participant path). The client must NOT derive
    // it — see domain Debt.viewerIsDebtor. The detail fetch (get_participant_debt_response) and the
    // list (GET /api/debts, computed per row for the viewer — slice 1A communal rows) populate it;
    // fact responses leave it null.
    @param:Json(name = "viewer_is_debtor")
    val viewerIsDebtor: Boolean? = null,
    // ADR-0049 §3.7 / §4 (slice 8e-3): true when this CLEARED Debt was forgiven by the creditor
    // ("算了，不用还了") rather than fully repaid — drives the "被请客/请客" headline (MemberDebtLabels)
    // and the §5.6 celebration fork. Always false for open / voided / repayment-cleared Debt; only
    // the server computes it (get_participant_debt_response), the client never derives it.
    @param:Json(name = "is_forgiven")
    val isForgiven: Boolean = false,
)

data class DebtListResponseDto(
    val items: List<DebtDto>,
)

/**
 * Response for `POST /api/debts/parse-bill` — transient OCR/vision suggestions for a debt bill.
 *
 * All fields are nullable except [sourceText]: an unconfigured provider returns an empty suggestion
 * so the Android form can still fall back to manual entry. The suggestion is not a fact; creating a
 * Debt still goes through [DebtCreateRequestDto].
 */
data class DebtBillParseResponseDto(
    val merchant: String? = null,
    @param:Json(name = "principal_amount_cents")
    val principalAmountCents: Long? = null,
    @param:Json(name = "installment_count")
    val installmentCount: Long? = null,
    @param:Json(name = "installment_period_months")
    val installmentPeriodMonths: Long? = null,
    @param:Json(name = "per_period_amount_cents")
    val perPeriodAmountCents: Long? = null,
    @param:Json(name = "repayment_day")
    val repaymentDay: Long? = null,
    @param:Json(name = "source_text")
    val sourceText: String = "",
    val confidence: Double? = null,
)

/**
 * Body for `POST /api/debts` — create one external/manual Debt (ADR-0049 §2 / §5.1).
 *
 * slice 8 submits the home-currency path only (`principalAmountCents`). The backend forces
 * `counterpartyType='external'` and `sourceType='manual'` for a public create — member Debt
 * arises server-side from bill-split accept (§5.2), and the foreign-currency path
 * (`original_currency` + `original_amount`) is deferred to a later slice. The backend marks
 * this body `additionalProperties=false`, so the DTO field set must stay a subset of the
 * schema (the contract gate's forward check is the forbid protection).
 */
data class DebtCreateRequestDto(
    val direction: String,
    @param:Json(name = "counterparty_type")
    val counterpartyType: String,
    @param:Json(name = "counterparty_label")
    val counterpartyLabel: String?,
    @param:Json(name = "principal_amount_cents")
    val principalAmountCents: Long,
    @param:Json(name = "source_type")
    val sourceType: String = "manual",
    // 8e-6e optional repayment-rhythm classification (see DebtKinds). DEFAULTED — DebtCreateRequest
    // defaults it server-side, so omitting it creates an `unspecified` Debt; the create form's picker
    // overrides it. `debt_kind` is a declared schema property (additionalProperties=false → the
    // contract gate's forward check passes only for declared fields).
    @param:Json(name = "debt_kind")
    val debtKind: String = "unspecified",
    // §B 完整 installment 期数 + 周期（均仅 kind=='installment' 时有效）。DEFAULTED/可空 — count 留空即不排期；
    // period 留空（null）后端默认按月（每月一期）= 国内分期的压倒性默认。两者都是 DebtCreateRequest 的已声明属性
    // （additionalProperties=false → 正向检查只对已声明字段通过）；后端 CHECK 把 count/period 配对，故 period
    // 只在 count 也给时随车（见 DebtMappers.toCreateRequest 的 chokepoint）。
    @param:Json(name = "installment_count")
    val installmentCount: Long? = null,
    @param:Json(name = "installment_period_months")
    val installmentPeriodMonths: Long? = null,
)

/**
 * Body for `POST /api/debts/{id}/repayments` — record one committed repayment fact (ADR-0049 §3.1,
 * slice 8c). slice 8c submits the home-currency path only (`amountCents`); the foreign-currency path
 * (`original_currency` + `original_amount` + `paid_at`) is deferred. [expectedRowVersion] is the
 * §2.1 stale-intent token (carries the Debt's `row_version`) + the §3.6 idempotency fingerprint
 * component. The backend marks this body `additionalProperties=false`, so the DTO field set must
 * stay a subset of the schema (the contract gate's forward check is the forbid protection).
 */
data class RepaymentCreateRequestDto(
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/**
 * Body for `POST /api/debts/{id}/adjustments` — record one signed principal-like correction
 * (ADR-0049 §3.3, slice 8c). [amountCents] is a signed home-currency delta (negative lowers
 * `remaining`, never below 0); [reason] is required. [expectedRowVersion] is the §2.1 stale-intent
 * token + §3.6 fingerprint component.
 */
data class DebtAdjustmentCreateRequestDto(
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val reason: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/**
 * Body for `POST /api/debts/{id}/void` — void an entire Debt (ADR-0049 §3.5, slice 8c). [reason] is
 * required. [expectedRowVersion] is the §2.1 stale-intent token + §3.6 fingerprint component.
 */
data class DebtVoidCreateRequestDto(
    val reason: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/**
 * Body for `POST /api/debts/{id}/forgive` — creditor forgives a member Debt's remaining
 * (ADR-0049 §3.7 / §4, slice 8e-3). No amount and no reason: the forgiven amount is the
 * `remaining_before` the backend snapshots under the §2.1 lock, and forgiveness needs no
 * justification. [expectedRowVersion] is the §2.1 stale-intent token + §3.6 fingerprint component.
 * The backend marks this body `additionalProperties=false`, so the DTO field set must stay a subset
 * of the schema (the contract gate's forward check is the forbid protection).
 */
data class DebtForgiveCreateRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/**
 * Body for `POST /api/debts/{id}/kind` — set / correct an existing Debt's repayment-rhythm
 * classification (ADR-0049 §7.0 / 8e-6e correction entry). [debtKind] is one of DebtKinds;
 * [expectedRowVersion] is the §2.1 stale-intent OCC token (a reclassification bumps `row_version`,
 * so two concurrent edits cannot both silently win) + the §3.6 fingerprint component. NOT
 * fold-changing — `debt_kind` gates only the external-debt payoff projection. The backend marks
 * this body `additionalProperties=false`, so the DTO field set must stay a subset of the schema
 * (the contract gate's forward check is the forbid protection).
 */
data class DebtKindSetRequestDto(
    @param:Json(name = "debt_kind")
    val debtKind: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)
