package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * ADR-0049 §6 (slice 7) — Android contract for the `debt_repayment` goal surface.
 *
 * A debt_repayment goal links explicit Debt ids and is "achieved" once all linked
 * Debts are cleared. The numeric spending-shape fields on [GoalDto] are `null` for a
 * debt goal; instead [GoalDto.debtRepayment] carries this evaluation block. Field
 * names mirror `DebtRepaymentEvaluation` / `DebtGoalLinkView` in the backend OpenAPI
 * snapshot (gated by `OpenApiContractGateTest`).
 */
data class DebtRepaymentEvaluationDto(
    @param:Json(name = "goal_version")
    val goalVersion: Int,
    // in_progress / achieved / not_evaluable (see DebtGoalEvaluationStates).
    @param:Json(name = "evaluation_state")
    val evaluationState: String,
    // §6/F13: a debt-voided linked Debt that is still unresolved (acknowledge or
    // remove it). True on both the not_evaluable and the achieved+integrity cases.
    @param:Json(name = "needs_review")
    val needsReview: Boolean,
    @param:Json(name = "achieved_at")
    val achievedAt: String? = null,
    @param:Json(name = "achieved_version")
    val achievedVersion: Int? = null,
    @param:Json(name = "linked_debts")
    val linkedDebts: List<DebtGoalLinkViewDto>,
    @param:Json(name = "voided_debt_public_ids")
    val voidedDebtPublicIds: List<String>,
    // ADR-0049 §7.0 / 8e-6b external-debt payoff projection — populated ONLY for a
    // pure-external plan (server-gated; null for member/mixed/thin/mixed-currency).
    // `trackingDays` = the observation window the velocity used (for a "按最近 N 天"
    // caption); `projectedPayoffDate` = ISO date string (no Moshi LocalDate adapter, so
    // String?, mirroring `achievedAt`). Both arrive together or both null.
    @param:Json(name = "tracking_days")
    val trackingDays: Int? = null,
    @param:Json(name = "projected_payoff_date")
    val projectedPayoffDate: String? = null,
    // ADR-0049 §7.0 / 8e-6c three-state. `targetDate` echoes the goal's payoff deadline (ISO date
    // string, null when unset / non-external — server-gated per §4); `threeState` ∈
    // {on_track, ahead, at_risk} is the projected-payoff month vs the deadline month, populated
    // ONLY when BOTH a deadline and a projection exist (else null — never editorialise, §7.0 R4).
    @param:Json(name = "target_date")
    val targetDate: String? = null,
    @param:Json(name = "three_state")
    val threeState: String? = null,
)

/** One linked Debt's shell inside a debt_repayment goal's evaluation block. */
data class DebtGoalLinkViewDto(
    @param:Json(name = "debt_public_id")
    val debtPublicId: String,
    // open / cleared / voided (derived fold, ADR-0049 §2).
    val status: String,
    // i_owe / owed_to_me (from the owner account's perspective).
    val direction: String,
    // member / external.
    @param:Json(name = "counterparty_type")
    val counterpartyType: String,
    @param:Json(name = "counterparty_label")
    val counterpartyLabel: String? = null,
    @param:Json(name = "principal_amount_cents")
    val principalAmountCents: Long,
    @param:Json(name = "remaining_amount_cents")
    val remainingAmountCents: Long,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
)

/**
 * Body for `POST /api/goals/{publicId}/debt-links` — replace a debt_repayment goal's
 * linked Debt set (the backend bumps `row_version` + `goal_version`). `debtPublicIds`
 * is the FULL new set (replace, not delta) and must be non-empty.
 *
 * `expectedRowVersion` is the client's last-seen OCC token; server returns 409
 * `state_conflict` on a stale snapshot.
 */
data class DebtGoalLinksReplaceRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "debt_public_ids")
    val debtPublicIds: List<String>,
)

/**
 * Body for `POST /api/goals/{publicId}/integrity-review/acknowledge` (§6/F13) —
 * "keep for audit": acknowledge an achieved goal version whose linked set carries a
 * debt-voided Debt, clearing `needs_review` for the current version. The other exit
 * (remove the voided Debt) goes through the link-replace route.
 */
data class DebtGoalIntegrityReviewRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/**
 * Body for `POST /api/goals/{publicId}/target-date` (ADR-0049 §7.0 / 8e-6c) — set or clear a
 * debt_repayment goal's payoff deadline. `expectedRowVersion` is the OCC token (the setter bumps
 * `row_version` only, never `goal_version`). `targetDate` is the ISO date to set, or `null` to
 * clear — the backend field is optional (a setter: omitted/null = clear), so Moshi's null-omission
 * naturally encodes the clear case (it never reaches the wire as an explicit null).
 */
data class DebtGoalTargetDateRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "target_date")
    val targetDate: String? = null,
)
