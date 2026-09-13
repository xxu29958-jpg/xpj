package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.normalizeExpenseCategory
import java.time.YearMonth

internal fun GoalDraft.validatedGoalDraft(): Result<GoalDraft> = runCatching {
    require(name.trim().isNotBlank()) { "请输入目标名称。" }
    require(targetAmountCents > 0L) { "目标金额必须大于 0。" }
    val parsedMonth = runCatching { YearMonth.parse(month.trim()).toString() }.getOrNull()
    require(parsedMonth != null) { "目标月份不正确。" }
    val currency = requireNotNull(CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)) { "原金额币种无法确认，请核对。" }
    copy(name = name.trim(), month = parsedMonth,
        homeCurrencyCode = currency.storageKey,
        category = category?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory))
}

data class PendingGoalCreation(val row: OutboxRow, val request: GoalCreateRequestDto?, val confirmed: Goal?) {
    val isDone: Boolean get() = row.status == PendingMutationStatus.Done
    val canRetry: Boolean get() = request?.isSupportedGoalCreation(row) == true &&
        row.status == PendingMutationStatus.Failed && (row.lastError?.startsWith("max_attempts_exceeded(") == true ||
        row.lastError in setOf("client_upgrade_required", "runtime_version_mismatch"))
    val canDrop: Boolean get() = row.status == PendingMutationStatus.Failed || row.status == PendingMutationStatus.Conflict
}

internal fun JsonAdapter<GoalCreateRequestDto>.readGoalCreation(row: OutboxRow): GoalCreateRequestDto? =
    runCatching { fromJson(row.payloadJson) }.getOrNull()

internal fun GoalCreateRequestDto.isSupportedGoalCreation(row: OutboxRow): Boolean =
    row.type == PendingMutationType.CreateGoal && row.expectedRowVersion == 0L &&
        !row.idempotencyKey.isNullOrBlank() && row.idempotencyKey.length <= 64 &&
        row.targetId == "goal_create:${row.idempotencyKey}" && goalType == "spending_limit" && period == "monthly" &&
        name.isNotBlank() && (targetAmountCents ?: 0L) > 0 && debtPublicIds == null &&
        runCatching { YearMonth.parse(month) }.isSuccess &&
        homeCurrencyCode != null && CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)?.storageKey == homeCurrencyCode

internal fun GoalCreateRequestDto.acceptsGoalCreationReceipt(row: OutboxRow, receipt: GoalDto): Boolean =
    isSupportedGoalCreation(row) && receipt.publicId.isNotBlank() && receipt.ledgerId == row.ledgerId &&
        receipt.goalType == goalType && receipt.period == period && receipt.status == "active" && receipt.rowVersion == 1L &&
        receipt.homeCurrencyCode == homeCurrencyCode && receipt.name == name && receipt.month == month &&
        receipt.category.orEmpty() == category.orEmpty() && receipt.targetAmountCents == targetAmountCents
