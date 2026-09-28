package com.ticketbox.ui.navigation

import com.ticketbox.data.remote.dto.BudgetCategoryDto
import com.ticketbox.data.remote.dto.BudgetExcludedCategoryDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.GoalDto

internal fun referenceBudget(month: String) = BudgetMonthlyDto(
    ledgerId = "correction-ledger", month = month, configured = true, homeCurrencyCode = "JPY", rowVersion = 1,
    totalAmountCents = 1200, rolloverAmountCents = 0, fixedAmountCents = 0, nonMonthlyAmountCents = 0,
    flexBudgetCents = 1200, spentAmountCents = 0, excludedAmountCents = 0, remainingAmountCents = 1200,
    overspentAmountCents = 0, excludedCategories = listOf("烘焙"),
    excludedBreakdown = listOf(BudgetExcludedCategoryDto("烘焙", 0, 0)),
    categoryBudgets = listOf(BudgetCategoryDto("烘焙", 300, 0, 300, 0)),
    updatedAt = "2026-09-01T00:00:00Z",
)

internal fun referenceGoal(publicId: String) = GoalDto(
    publicId = publicId, ledgerId = "correction-ledger",
    name = if (publicId == "bakery-goal") "烘焙限额" else "另一个消费目标",
    goalType = "spending_limit", period = "monthly", month = "2026-02", category = "烘焙",
    targetAmountCents = 1200, spentAmountCents = 0, remainingAmountCents = 1200,
    progressPercent = 0, progressState = "on_track", status = "active",
    createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z",
    rowVersion = 1, archivedAt = null, homeCurrencyCode = "JPY",
)
