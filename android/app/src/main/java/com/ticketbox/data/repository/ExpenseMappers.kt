package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.remote.dto.CategoryStatsDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.FrequentMerchantDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.FrequentMerchant
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.ServerSettings

fun ExpenseDto.toDomain(): Expense = Expense(
    id = id,
    amountCents = amountCents,
    merchant = merchant,
    category = category,
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

fun ExpenseDto.toEntity(): ExpenseEntity = ExpenseEntity(
    serverId = id,
    amountCents = amountCents,
    merchant = merchant,
    category = category,
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

fun ExpenseEntity.toDomain(): Expense = Expense(
    id = serverId,
    amountCents = amountCents,
    merchant = merchant,
    category = category,
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
    category = category,
    note = note,
    expenseTime = expenseTime,
    tags = tags,
    valueScore = valueScore,
    regretScore = regretScore,
)

fun MonthlyStatsDto.toDomain(): MonthlyStats = MonthlyStats(
    month = month,
    totalAmountCents = totalAmountCents,
    count = count,
    byCategory = byCategory.map { it.toDomain() },
)

fun CategoryStatsDto.toDomain(): CategoryStats = CategoryStats(
    category = category,
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

fun CategoryRuleDto.toDomain(): CategoryRule = CategoryRule(
    id = id,
    keyword = keyword,
    category = category,
    enabled = enabled,
    priority = priority,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

fun ServerSettingsDto.toDomain(): ServerSettings = ServerSettings(
    maxUploadSizeMb = maxUploadSizeMb,
    generateThumbnail = generateThumbnail,
    deleteImageAfterConfirm = deleteImageAfterConfirm,
    deleteImageAfterDays = deleteImageAfterDays,
    ocrProvider = ocrProvider,
    pendingCount = pendingCount,
    confirmedCount = confirmedCount,
    rejectedCount = rejectedCount,
    suspectedDuplicateCount = suspectedDuplicateCount,
    uploadStorageBytes = uploadStorageBytes,
)
