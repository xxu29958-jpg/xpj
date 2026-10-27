package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalCreateRequest
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.GoalUpdateRequest
import com.ticketbox.domain.model.normalizeExpenseCategory

fun GoalDto.toDomain(): Goal = Goal(
    publicId = publicId,
    ledgerId = ledgerId,
    name = name,
    goalType = goalType,
    period = period,
    month = month.orEmpty(),
    category = category?.let(::normalizeExpenseCategory),
    targetAmountCents = targetAmountCents,
    spentAmountCents = spentAmountCents,
    remainingAmountCents = remainingAmountCents,
    progressPercent = progressPercent,
    progressState = GoalProgressState.fromApiValue(progressState),
    status = status,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
    archivedAt = archivedAt,
    debtRepayment = debtRepayment?.toDomain(),
    homeCurrencyCode = homeCurrencyCode,
    undatedExpenseCount = undatedExpenseCount,
)

fun GoalDraft.toRequest(): GoalCreateRequest = GoalCreateRequest(
    name = name.trim(),
    month = month.trim(),
    targetAmountCents = targetAmountCents,
    homeCurrencyCode = homeCurrencyCode,
    category = category.cleanCategoryOrNull(),
)

fun GoalUpdate.toRequest(): GoalUpdateRequest = GoalUpdateRequest(
    expectedRowVersion = expectedRowVersion,
    homeCurrencyCode = homeCurrencyCode,
    name = name?.trim()?.takeIf { it.isNotBlank() },
    month = month?.trim()?.takeIf { it.isNotBlank() },
    targetAmountCents = targetAmountCents,
    // PATCH needs to distinguish "category omitted" (leave unchanged) from an
    // explicit blank category (clear to the all-spending scope). Moshi omits
    // nulls, so preserve "" here; the backend normalizes blank to SQL NULL.
    category = category?.trim()?.let { if (it.isBlank()) "" else normalizeExpenseCategory(it) },
)

private fun String?.cleanCategoryOrNull(): String? =
    this?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory)

internal fun GoalUpdate.matchesSubmittedRequest(original: com.ticketbox.domain.model.GoalUpdateRequest?): Boolean =
    toRequest() == original
