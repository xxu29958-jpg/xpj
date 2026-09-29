package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * ADR-0049 §杠杆③ (slice 3a) — Android contract for the NLS repayment-capture inbox.
 *
 * Mirrors backend `RepaymentDraftResponse` / `RepaymentDraftListResponse` / the create/confirm/dismiss
 * request bodies in the committed OpenAPI snapshot (gated by `OpenApiContractGateTest`).
 * Originals remain captured input; unknown converted home money is null. Status and committed
 * identities come from the server. Human review can submit distinct money without rewriting capture.
 */
data class RepaymentDraftDto(
    @param:Json(name = "public_id")
    val publicId: String,
    // alipay / jd / meituan / wechat / bank_sms / bank_app / other (the capturing channel).
    val source: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
    @param:Json(name = "merchant_label")
    val merchantLabel: String? = null,
    @param:Json(name = "captured_at")
    val capturedAt: String,
    // pending / confirmed / dismissed (see RepaymentDraftStatuses).
    val status: String,
    // §杠杆③ 3b: the server-suggested target Debt (fuzzy counterparty_label + amount), populated
    // ONLY for a pending draft and recomputed every list (ephemeral — never stored). null = no
    // confident match → the user picks manually. The inbox pre-selects this Debt in the picker.
    @param:Json(name = "suggested_debt_public_id")
    val suggestedDebtPublicId: String? = null,
    @param:Json(name = "committed_debt_public_id")
    val committedDebtPublicId: String? = null,
    @param:Json(name = "committed_repayment_public_id")
    val committedRepaymentPublicId: String? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "resolved_at")
    val resolvedAt: String? = null,
    @param:Json(name = "original_currency_code")
    val originalCurrencyCode: String = homeCurrencyCode,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long = requireNotNull(amountCents),
)

data class RepaymentDraftListResponseDto(
    val items: List<RepaymentDraftDto>,
)

/**
 * Body for `POST /api/repayment-drafts` — capture one NLS repayment as a pending draft (§杠杆③).
 *
 * Original currency and decimal amount are explicit; legacy amountCents denotes CNY minor units.
 * The installation currency is server-owned. [notificationKey] is the
 * per-post identity hash (`notificationIdentityKey(sbn.key, sbn.postTime)`), the PRIMARY dedup axis so
 * a re-posted notification does not twin the draft (Moshi drops nulls → absent = content+window dedup).
 * The backend marks this body `additionalProperties=false`, so the DTO field set must stay a subset of
 * the schema (the contract gate's forward check is the forbid protection).
 */
data class RepaymentDraftCreateRequestDto(
    val source: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long? = null,
    @param:Json(name = "merchant_label")
    val merchantLabel: String? = null,
    @param:Json(name = "captured_at")
    val capturedAt: String? = null,
    @param:Json(name = "notification_key")
    val notificationKey: String? = null,
    @param:Json(name = "original_currency")
    val originalCurrency: String? = null,
    @param:Json(name = "original_amount")
    val originalAmount: String? = null,
)

/**
 * Body for `POST /api/repayment-drafts/{id}/confirm` — confirm a draft against a chosen Debt (§杠杆③).
 *
 * [targetDebtPublicId] is the open external/manual Debt the captured repayment pays down (the user
 * picks it in slice 3a). Confirm commits one `Repayment` → fold-changing, so [expectedRowVersion] is
 * the chosen Debt's §2.1 stale-intent token + §3.6 idempotency fingerprint component (REQUIRED). The
 * route also carries an ADR-0042 `Idempotency-Key` header (supplied by the repository).
 */
/** Body for `POST /api/expenses/{id}/repayment-draft`. */
data class ExpenseRepaymentDraftCreateRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/** Body for `POST /api/repayment-drafts/{id}/confirm`. */
data class RepaymentDraftConfirmRequestDto(
    @param:Json(name = "target_debt_public_id")
    val targetDebtPublicId: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "original_currency")
    val originalCurrency: String? = null,
    @param:Json(name = "original_amount")
    val originalAmount: String? = null,
)

/**
 * Body for `POST /api/repayment-drafts/{id}/dismiss` — latch a pending draft dismissed (§杠杆③).
 * A no-field body (`extra=forbid` → the backend requires `{}`); Moshi serializes the empty instance to
 * `{}`. Dismiss commits no `Repayment`, so it carries no OCC token and no idempotency key.
 */
class RepaymentDraftDismissRequestDto
