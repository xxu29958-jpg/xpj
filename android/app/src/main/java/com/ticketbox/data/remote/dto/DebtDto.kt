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
)

data class DebtListResponseDto(
    val items: List<DebtDto>,
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
)
