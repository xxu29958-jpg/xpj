package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.remote.dto.CategoryStatsDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.FrequentMerchantDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.NotificationDraftRequestDto
import com.ticketbox.data.remote.dto.RecurringCandidateItemDto
import com.ticketbox.data.remote.dto.DataQualitySummaryDto
import com.ticketbox.data.remote.dto.RuleApplicationBatchDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.remote.dto.RuleApplyPreviewItemDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.TagStatsDto
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.FrequentMerchant
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplicationRollback
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.RuleApplyPreviewItem
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.TagStats
import com.ticketbox.domain.model.normalizeExpenseCategory

fun ExpenseDto.toDomain(): Expense = Expense(
    id = id,
    publicId = requiredPublicId(),
    amountCents = amountCents,
    merchant = merchant,
    category = normalizeExpenseCategory(category),
    note = note,
    source = source,
    imagePath = imagePath,
    thumbnailPath = thumbnailPath,
    imageHash = imageHash,
    rawText = rawText,
    confidence = confidence,
    duplicateStatus = duplicateStatus,
    duplicateOfId = duplicateOfId,
    duplicateReason = duplicateReason,
    tags = tags,
    valueScore = valueScore,
    regretScore = regretScore,
    status = status,
    expenseTime = expenseTime,
    createdAt = createdAt,
    updatedAt = updatedAt,
    confirmedAt = confirmedAt,
    rejectedAt = rejectedAt,
)

fun ExpenseDto.toEntity(ledgerId: String): ExpenseEntity = ExpenseEntity(
    ledgerId = ledgerId,
    serverId = id,
    publicId = requiredPublicId(),
    amountCents = amountCents,
    merchant = merchant,
    category = normalizeExpenseCategory(category),
    note = note,
    source = source,
    thumbnailPath = thumbnailPath,
    imageHash = imageHash,
    rawText = rawText,
    duplicateStatus = duplicateStatus,
    duplicateOfId = duplicateOfId,
    duplicateReason = duplicateReason,
    tags = tags,
    valueScore = valueScore,
    regretScore = regretScore,
    status = status,
    expenseTime = expenseTime,
    createdAt = createdAt,
    confirmedAt = confirmedAt,
    updatedAt = updatedAt,
)

private fun ExpenseDto.requiredPublicId(): String {
    return publicId
        ?.trim()
        ?.takeIf { it.isNotBlank() }
        ?: throw RepositoryException("账本版本过旧，请重启电脑上的小票夹后再试。")
}

fun ExpenseEntity.toDomain(): Expense = Expense(
    id = serverId,
    publicId = publicId,
    amountCents = amountCents,
    merchant = merchant,
    category = normalizeExpenseCategory(category),
    note = note,
    source = source,
    imagePath = null,
    thumbnailPath = thumbnailPath,
    imageHash = imageHash,
    rawText = rawText,
    confidence = null,
    duplicateStatus = duplicateStatus,
    duplicateOfId = duplicateOfId,
    duplicateReason = duplicateReason,
    tags = tags,
    valueScore = valueScore,
    regretScore = regretScore,
    status = status,
    expenseTime = expenseTime,
    createdAt = createdAt,
    updatedAt = updatedAt ?: createdAt,
    confirmedAt = confirmedAt,
    rejectedAt = null,
)

fun ExpenseDraft.toRequest(): ExpenseUpdateRequest = ExpenseUpdateRequest(
    amountCents = amountCents,
    merchant = merchant,
    category = normalizeExpenseCategory(category),
    note = note,
    expenseTime = expenseTime,
    tags = tags,
    valueScore = valueScore,
    regretScore = regretScore,
)

fun NotificationDraft.toRequest(): NotificationDraftRequestDto = NotificationDraftRequestDto(
    source = source.apiValue,
    amountCents = amountCents,
    merchant = merchant?.trim()?.takeIf { it.isNotBlank() },
    category = normalizeExpenseCategory(category),
    expenseTime = expenseTime,
)

fun MonthlyStatsDto.toDomain(): MonthlyStats = MonthlyStats(
    month = month,
    totalAmountCents = totalAmountCents,
    count = count,
    byCategory = byCategory.map { it.toDomain() },
    byTag = byTag.map { it.toDomain() },
)

fun CategoryStatsDto.toDomain(): CategoryStats = CategoryStats(
    category = normalizeExpenseCategory(category),
    amountCents = amountCents,
    count = count,
)

fun TagStatsDto.toDomain(): TagStats = TagStats(
    tag = tag,
    amountCents = amountCents,
    count = count,
)

fun LifestyleStatsDto.toDomain(): LifestyleStats = LifestyleStats(
    month = month,
    aiSubscriptionAmountCents = aiSubscriptionAmountCents,
    digitalAmountCents = digitalAmountCents,
    maxExpense = maxExpense?.toDomain(),
    recent7DaysAmountCents = recent7DaysAmountCents,
    frequentMerchants = frequentMerchants.map { it.toDomain() },
)

fun FrequentMerchantDto.toDomain(): FrequentMerchant = FrequentMerchant(
    merchant = merchant,
    count = count,
)

fun RecurringCandidateItemDto.toDomain(): RecurringCandidate = RecurringCandidate(
    merchant = merchant,
    amountCents = amountCents,
    occurrenceCount = occurrenceCount,
    lastSeenAt = lastSeenAt,
    confidence = confidence,
    reason = reason,
)

fun DataQualitySummaryDto.toDomain(): DataQualitySummary = DataQualitySummary(
    pendingTotal = pendingTotal,
    missingAmount = missingAmount,
    missingMerchant = missingMerchant,
    missingCategory = missingCategory,
    suspectedDuplicates = suspectedDuplicates,
    confirmedWithoutImage = confirmedWithoutImage,
    readyToConfirm = readyToConfirm,
    oldestPendingAgeDays = oldestPendingAgeDays,
    generatedAt = generatedAt,
)

fun CategoryRuleDto.toDomain(): CategoryRule = CategoryRule(
    id = id,
    keyword = keyword,
    category = normalizeExpenseCategory(category),
    enabled = enabled,
    priority = priority,
    amountMinCents = amountMinCents,
    amountMaxCents = amountMaxCents,
    sourceContains = sourceContains,
    tagContains = tagContains,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

fun RuleApplicationBatchDto.toDomain(): RuleApplicationBatch = RuleApplicationBatch(
    publicId = publicId,
    status = status,
    pendingScanned = pendingScanned,
    changedCount = changedCount,
    createdAt = createdAt,
    rolledBackAt = rolledBackAt,
)

fun RuleApplicationRollbackDto.toDomain(): RuleApplicationRollback = RuleApplicationRollback(
    publicId = publicId,
    status = status,
    changed = changed,
    skipped = skipped,
    rolledBackAt = rolledBackAt,
)

fun RuleApplyPreviewItemDto.toDomain(): RuleApplyPreviewItem = RuleApplyPreviewItem(
    id = id,
    merchant = merchant,
    currentCategory = normalizeExpenseCategory(currentCategory),
    suggestedCategory = normalizeExpenseCategory(suggestedCategory),
    ruleKeyword = ruleKeyword,
    reason = reason,
)

fun RuleApplyConfirmedResponseDto.toDomain(): RuleApplyConfirmedResult = RuleApplyConfirmedResult(
    dryRun = dryRun,
    confirmedScanned = confirmedScanned,
    changedCount = changedCount,
    items = items.map { it.toDomain() },
    skippedNonDefaultCategory = skippedNonDefaultCategory,
    noMatchCount = noMatchCount,
    unchangedCount = unchangedCount,
    conflictCount = conflictCount,
    scanLimitReached = scanLimitReached,
    scanLimit = scanLimit,
    previewToken = previewToken,
)

fun ServerSettingsDto.toDomain(): ServerSettings = ServerSettings(
    accountName = accountName,
    ledgerId = ledgerId,
    ledgerName = ledgerName,
    ledgerIsDefault = ledgerIsDefault,
    deviceName = deviceName,
    role = role,
    status = status,
    storageStatus = storageStatus,
    pendingCount = pendingCount,
    confirmedCount = confirmedCount,
    rejectedCount = rejectedCount,
    suspectedDuplicateCount = suspectedDuplicateCount,
    uploadStorageBytes = uploadStorageBytes,
    latestUploadAt = latestUploadAt,
)
