package com.ticketbox.domain.model

/**
 * ADR-0049 §6 (slice 7) debt_repayment goal domain models.
 *
 * A [Goal] with `goalType == "debt_repayment"` carries a [DebtRepaymentEvaluation]
 * (the goal's CURRENT version) instead of the spending-shape numeric fields. The
 * raw backend string values (evaluation state, link fold status, direction,
 * counterparty type) are kept as `String` and mapped to localized labels in the UI
 * layer — mirroring the BillSplit status pattern — with the canonical values pinned
 * by the value objects below so branching/coloring logic does not hardcode literals.
 */
object DebtGoalEvaluationStates {
    const val IN_PROGRESS = "in_progress"
    const val ACHIEVED = "achieved"
    const val NOT_EVALUABLE = "not_evaluable"
}

object DebtLinkStatuses {
    const val OPEN = "open"
    const val CLEARED = "cleared"
    const val VOIDED = "voided"
}

object DebtDirections {
    /** The ledger owner owes the counterparty (owner is the debtor). */
    const val I_OWE = "i_owe"

    /** The counterparty owes the ledger owner (owner is the creditor). */
    const val OWED_TO_ME = "owed_to_me"
}

object DebtCounterpartyTypes {
    const val MEMBER = "member"
    const val EXTERNAL = "external"
}

data class DebtGoalLink(
    val debtPublicId: String,
    val status: String,
    val direction: String,
    val counterpartyType: String,
    val counterpartyLabel: String?,
    val principalAmountCents: Long,
    val remainingAmountCents: Long,
    val homeCurrencyCode: String,
) {
    val isVoided: Boolean get() = status == DebtLinkStatuses.VOIDED
    val isCleared: Boolean get() = status == DebtLinkStatuses.CLEARED
    val isOpen: Boolean get() = status == DebtLinkStatuses.OPEN
}

data class DebtRepaymentEvaluation(
    val goalVersion: Int,
    val evaluationState: String,
    val needsReview: Boolean,
    val achievedAt: String?,
    val achievedVersion: Int?,
    val linkedDebts: List<DebtGoalLink>,
    val voidedDebtPublicIds: List<String>,
) {
    val isAchieved: Boolean get() = evaluationState == DebtGoalEvaluationStates.ACHIEVED
    val isInProgress: Boolean get() = evaluationState == DebtGoalEvaluationStates.IN_PROGRESS
    val isNotEvaluable: Boolean get() = evaluationState == DebtGoalEvaluationStates.NOT_EVALUABLE

    /** Linked Debts whose fold is still open (not yet cleared, not voided). */
    val openDebts: List<DebtGoalLink> get() = linkedDebts.filter { it.isOpen }

    /** Linked Debts that have been debt-voided (§6/F13 review trigger). */
    val voidedDebts: List<DebtGoalLink> get() = linkedDebts.filter { it.isVoided }

    /**
     * The non-voided link set, as `debt_public_id`s — the replacement set submitted to
     * the link-replace route to take the voided Debt(s) out of the goal (one integrity
     * exit). Empty when every link is voided (the UI must guard: replace needs ≥1 id).
     */
    val nonVoidedDebtPublicIds: List<String>
        get() = linkedDebts.filterNot { it.isVoided }.map { it.debtPublicId }
}
