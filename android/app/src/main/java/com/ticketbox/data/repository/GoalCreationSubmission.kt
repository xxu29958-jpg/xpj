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

internal fun GoalCreateRequestDto.validatedGoalCreation(): Result<GoalCreateRequestDto> = runCatching {
    require(period == "monthly") { "目标周期无法确认，请保留草稿并核对。" }
    when (goalType) {
        "spending_limit" -> {
            require(debtPublicIds == null) { "消费目标不能关联欠款。" }
            GoalDraft(name, requireNotNull(month) { "目标月份不正确。" },
                requireNotNull(targetAmountCents) { "请输入目标金额。" }, category,
                requireNotNull(homeCurrencyCode) { "原金额币种无法确认，请核对。" }).validatedGoalDraft().getOrThrow().toRequest()
        }
        "debt_repayment" -> {
            require(month == null && category == null && targetAmountCents == null && homeCurrencyCode == null) {
                "还债目标只接受名称和明确关联的欠款。"
            }
            val cleanName = name.trim()
            require(cleanName.isNotEmpty() && cleanName.length <= 80) { "请输入不超过 80 字的目标名称。" }
            val ids = debtPublicIds.orEmpty().map(String::trim).filter(String::isNotEmpty).distinct()
            require(ids.isNotEmpty()) { "请至少关联一笔欠款。" }
            copy(name = cleanName, debtPublicIds = ids)
        }
        else -> error("原创建类型无法确认，请保留草稿并核对。")
    }
}

suspend fun GoalEditActions.create(binding: LogicalSessionBinding, draft: GoalDraft, creationKey: String): Result<Long> {
    val clean = draft.validatedGoalDraft().getOrElse { return Result.failure(it) }
    return create(binding, clean.toRequest(), creationKey)
}

suspend fun GoalEditActions.createDebtGoal(binding: LogicalSessionBinding, name: String,
    debtPublicIds: List<String>, creationKey: String): Result<Long> {
    val request = GoalCreateRequestDto(name = name, goalType = "debt_repayment", debtPublicIds = debtPublicIds)
        .validatedGoalCreation().getOrElse { return Result.failure(it) }
    return create(binding, request, creationKey)
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
        row.targetId == "goal_create:${row.idempotencyKey}" && period == "monthly" && name.isNotBlank() &&
        when (goalType) {
            "spending_limit" -> isSupportedSpendingCreation()
            "debt_repayment" -> isSupportedDebtCreation()
            else -> false
        }

private fun GoalCreateRequestDto.isSupportedSpendingCreation(): Boolean =
    (targetAmountCents ?: 0L) > 0 && debtPublicIds == null &&
        runCatching { YearMonth.parse(month) }.isSuccess &&
        homeCurrencyCode != null && CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)?.storageKey == homeCurrencyCode

private fun GoalCreateRequestDto.isSupportedDebtCreation(): Boolean =
    month == null && category == null && targetAmountCents == null && homeCurrencyCode == null && name.length <= 80 &&
        !debtPublicIds.isNullOrEmpty() && debtPublicIds.all { it.isNotBlank() && it == it.trim() } &&
        debtPublicIds.distinct().size == debtPublicIds.size

internal fun GoalCreateRequestDto.acceptsGoalCreationReceipt(row: OutboxRow, receipt: GoalDto): Boolean =
    isSupportedGoalCreation(row) && receipt.publicId.isNotBlank() && receipt.ledgerId == row.ledgerId &&
        receipt.goalType == goalType && receipt.period == period && receipt.status == "active" && receipt.rowVersion == 1L &&
        receipt.name == name && when (goalType) {
            "spending_limit" -> acceptsSpendingCreationReceipt(receipt)
            "debt_repayment" -> acceptsDebtCreationReceipt(receipt)
            else -> false
        }

private fun GoalCreateRequestDto.acceptsSpendingCreationReceipt(receipt: GoalDto): Boolean =
    receipt.homeCurrencyCode == homeCurrencyCode && receipt.month == month &&
        receipt.category.orEmpty() == category.orEmpty() && receipt.targetAmountCents == targetAmountCents

private fun GoalCreateRequestDto.acceptsDebtCreationReceipt(receipt: GoalDto): Boolean {
    val evaluation = receipt.debtRepayment ?: return false
    val ids = evaluation.linkedDebts.map { it.debtPublicId }
    return receipt.month == null && receipt.category == null && receipt.targetAmountCents == null &&
        receipt.spentAmountCents == null && receipt.remainingAmountCents == null && receipt.progressPercent == null &&
        receipt.homeCurrencyCode == null && evaluation.goalVersion == 1 &&
        ids.size == debtPublicIds?.size && ids.toSet() == debtPublicIds?.toSet()
}
