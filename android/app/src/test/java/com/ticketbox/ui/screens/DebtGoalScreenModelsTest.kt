package com.ticketbox.ui.screens

import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtGoalEvaluationStates
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtRepaymentEvaluation
import com.ticketbox.domain.model.GOAL_TYPE_DEBT_REPAYMENT
import com.ticketbox.domain.model.GOAL_TYPE_SPENDING_LIMIT
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DebtGoalScreenModelsTest {
    @Test
    fun summaryCountsOnlyActiveDebtGoals() {
        val summary = debtGoalListSummary(
            goals = listOf(
                debtGoal("external", links = listOf(link("a"), link("b", DebtLinkStatuses.CLEARED))),
                debtGoal(
                    "done",
                    state = DebtGoalEvaluationStates.ACHIEVED,
                    links = listOf(link("c", DebtLinkStatuses.CLEARED)),
                ),
                debtGoal("archived", archived = true, links = listOf(link("d"))),
                spendingGoal(),
            ),
            isLoading = false,
        )

        assertEquals(2, summary.activeGoalCount)
        assertEquals(1, summary.achievedGoalCount)
        assertEquals(3, summary.linkedDebtCount)
        assertEquals(1, summary.openDebtCount)
    }

    @Test
    fun summaryTreatsReviewAndNotEvaluableGoalsAsAttention() {
        val summary = debtGoalListSummary(
            goals = listOf(
                debtGoal("review", needsReview = true, links = listOf(link("a"))),
                debtGoal("not-evaluable", state = DebtGoalEvaluationStates.NOT_EVALUABLE, links = listOf(link("b"))),
            ),
            isLoading = false,
        )

        assertEquals(2, summary.reviewGoalCount)
    }

    @Test
    fun summaryOnlyShowsInitialLoadingWhenThereIsNoReadableGoal() {
        assertTrue(debtGoalListSummary(emptyList(), isLoading = true).loadingWithoutData)
        assertFalse(
            debtGoalListSummary(
                goals = listOf(debtGoal("existing", links = listOf(link("a")))),
                isLoading = true,
            ).loadingWithoutData,
        )
    }
}

private fun debtGoal(
    name: String,
    state: String = DebtGoalEvaluationStates.IN_PROGRESS,
    needsReview: Boolean = false,
    archived: Boolean = false,
    links: List<DebtGoalLink>,
): Goal = goal(
    name = name,
    type = GOAL_TYPE_DEBT_REPAYMENT,
    archived = archived,
    evaluation = DebtRepaymentEvaluation(
        goalVersion = 1,
        evaluationState = state,
        needsReview = needsReview,
        achievedAt = null,
        achievedVersion = null,
        linkedDebts = links,
        voidedDebtPublicIds = links.filter { it.isVoided }.map { it.debtPublicId },
    ),
)

private fun spendingGoal(): Goal = goal(
    name = "spending",
    type = GOAL_TYPE_SPENDING_LIMIT,
    archived = false,
    evaluation = null,
)

private fun goal(
    name: String,
    type: String,
    archived: Boolean,
    evaluation: DebtRepaymentEvaluation?,
): Goal = Goal(
    publicId = "goal-$name",
    ledgerId = "ledger-1",
    name = name,
    goalType = type,
    period = "monthly",
    month = "2026-07",
    category = null,
    targetAmountCents = 0,
    spentAmountCents = 0,
    remainingAmountCents = 0,
    progressPercent = 0,
    progressState = GoalProgressState.Idle,
    status = if (archived) "archived" else "active",
    createdAt = "2026-07-01T00:00:00Z",
    updatedAt = "2026-07-01T00:00:00Z",
    rowVersion = 1,
    archivedAt = if (archived) "2026-07-01T01:00:00Z" else null,
    debtRepayment = evaluation,
)

private fun link(
    id: String,
    status: String = DebtLinkStatuses.OPEN,
): DebtGoalLink = DebtGoalLink(
    debtPublicId = "debt-$id",
    status = status,
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyLabel = null,
    principalAmountCents = 10000,
    remainingAmountCents = if (status == DebtLinkStatuses.CLEARED) 0 else 6000,
    homeCurrencyCode = "CNY",
)
