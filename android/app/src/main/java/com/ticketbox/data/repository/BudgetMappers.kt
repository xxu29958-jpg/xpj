package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BudgetCategoryDto
import com.ticketbox.data.remote.dto.BudgetCategoryRequestDto
import com.ticketbox.data.remote.dto.BudgetExcludedCategoryDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.domain.model.BudgetCategoryBudget
import com.ticketbox.domain.model.BudgetCategoryDraft
import com.ticketbox.domain.model.BudgetExcludedCategory
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.normalizeExpenseCategory

fun BudgetMonthlyDto.toDomain(): BudgetMonthly = BudgetMonthly(
    ledgerId = ledgerId,
    month = month,
    configured = configured,
    totalAmountCents = totalAmountCents,
    rolloverAmountCents = rolloverAmountCents,
    fixedAmountCents = fixedAmountCents,
    nonMonthlyAmountCents = nonMonthlyAmountCents,
    flexBudgetCents = flexBudgetCents,
    spentAmountCents = spentAmountCents,
    excludedAmountCents = excludedAmountCents,
    remainingAmountCents = remainingAmountCents,
    overspentAmountCents = overspentAmountCents,
    excludedCategories = excludedCategories.map(::normalizeExpenseCategory).distinct(),
    excludedBreakdown = excludedBreakdown.map { it.toDomain() },
    categoryBudgets = categoryBudgets.map { it.toDomain() },
    updatedAt = updatedAt,
    rowVersion = rowVersion,
)

private fun BudgetCategoryDto.toDomain(): BudgetCategoryBudget = BudgetCategoryBudget(
    category = normalizeExpenseCategory(category),
    amountCents = amountCents,
    spentAmountCents = spentAmountCents,
    remainingAmountCents = remainingAmountCents,
    overspentAmountCents = overspentAmountCents,
)

private fun BudgetExcludedCategoryDto.toDomain(): BudgetExcludedCategory = BudgetExcludedCategory(
    category = normalizeExpenseCategory(category),
    amountCents = amountCents,
    count = count,
)

fun BudgetMonthlyUpdate.toRequest(): BudgetMonthlyUpdateRequestDto = BudgetMonthlyUpdateRequestDto(
    totalAmountCents = totalAmountCents,
    nonMonthlyAmountCents = nonMonthlyAmountCents,
    rolloverAmountCents = rolloverAmountCents,
    excludedCategories = excludedCategories.map(::normalizeExpenseCategory).distinct(),
    categoryBudgets = categoryBudgets
        .map { it.normalized() }
        .distinctBy { it.category }
        .map {
            BudgetCategoryRequestDto(
                category = it.category,
                amountCents = it.amountCents,
            )
        },
)

private fun BudgetCategoryDraft.normalized(): BudgetCategoryDraft = copy(
    category = normalizeExpenseCategory(category),
)
