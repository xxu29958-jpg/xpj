package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * ADR-0049 §3.2 (slice 8d) — Android contract for the member repayment-proposal surface.
 *
 * Mirrors backend `MemberRepaymentProposalResponse` / `...ListResponse` / the four request bodies
 * in the committed OpenAPI snapshot (gated by `OpenApiContractGateTest`). Money is home-currency
 * minor units (cents); `proposed`/`confirmed` are server-frozen (§2.2) and never recomputed on the
 * client. The proposal response carries no ledger id (it is not redactable across accounts), so
 * the cross-ledger creditor reads it through the participant-scoped routes without leaking the
 * counterparty's ledger internals.
 */
data class MemberRepaymentProposalDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "debt_public_id")
    val debtPublicId: String,
    // pending / confirmed / partially_confirmed / rejected / withdrawn / expired / superseded.
    val status: String,
    @param:Json(name = "proposed_amount_cents")
    val proposedAmountCents: Long,
    @param:Json(name = "confirmed_amount_cents")
    val confirmedAmountCents: Long? = null,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
    @param:Json(name = "original_currency_code")
    val originalCurrencyCode: String? = null,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long? = null,
    @param:Json(name = "paid_at")
    val paidAt: String,
    val note: String? = null,
    @param:Json(name = "expires_at")
    val expiresAt: String,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "resolved_at")
    val resolvedAt: String? = null,
    @param:Json(name = "supersedes_proposal_public_id")
    val supersedesProposalPublicId: String? = null,
    @param:Json(name = "committed_repayment_public_id")
    val committedRepaymentPublicId: String? = null,
)

data class MemberRepaymentProposalListResponseDto(
    val items: List<MemberRepaymentProposalDto>,
)

/**
 * Body for `POST /api/debts/{id}/repayment-proposals` — the debtor's "I paid" proposal (§3.2).
 *
 * slice 8d submits the home-currency path only ([proposedAmountCents]); the optional
 * foreign-currency fields (`original_currency_code` + `original_amount` + `paid_at` + `expires_at`)
 * are deferred (a subset of the schema, so the contract gate's forward check passes). Creating a
 * proposal does NOT change the fold (a pending intent, not a fact), so there is no
 * `expected_row_version` — the parent CAS happens only on confirm. [supersedesProposalPublicId] is
 * omitted (Moshi drops nulls) for a first proposal; replacing an existing pending one names it so a
 * delayed request cannot overwrite a newer unseen proposal. The backend marks this body
 * `additionalProperties=false`, so the DTO field set must stay a subset of the schema.
 */
data class MemberRepaymentProposalCreateRequestDto(
    @param:Json(name = "proposed_amount_cents")
    val proposedAmountCents: Long,
    val note: String? = null,
    @param:Json(name = "supersedes_proposal_public_id")
    val supersedesProposalPublicId: String? = null,
)

/**
 * Body for `POST /api/debts/{id}/repayment-proposals/{pid}/confirm` — the creditor confirms (§3.2).
 *
 * [confirmedAmountCents] is the home amount actually accepted; null confirms the full proposed
 * amount (Moshi drops the null key). A partial confirm (`< proposed`) commits a partial repayment.
 * Confirm is fold-changing, so [expectedRowVersion] is the §2.1 stale-intent token + §3.6
 * idempotency fingerprint component (REQUIRED).
 */
data class MemberRepaymentProposalConfirmRequestDto(
    @param:Json(name = "confirmed_amount_cents")
    val confirmedAmountCents: Long? = null,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/**
 * Body for `POST /api/debts/{id}/repayment-proposals/{pid}/reject` — the creditor rejects (§3.2).
 * A no-field body (`extra=forbid` → the backend requires `{}`); Moshi serializes the empty instance
 * to `{}`. Carries an `Idempotency-Key` header (supplied by the repository), not a body field.
 */
class MemberRepaymentProposalRejectRequestDto

/**
 * Body for `POST /api/debts/{id}/repayment-proposals/{pid}/withdraw` — the debtor withdraws (§3.2).
 * A no-field body (`extra=forbid` → the backend requires `{}`); Moshi serializes the empty instance
 * to `{}`. Carries an `Idempotency-Key` header (supplied by the repository), not a body field.
 */
class MemberRepaymentProposalWithdrawRequestDto
