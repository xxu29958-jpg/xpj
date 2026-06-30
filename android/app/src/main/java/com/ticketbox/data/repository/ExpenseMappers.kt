package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.remote.dto.CategoryStatsDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.FrequentMerchantDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.NotificationDraftRequestDto
import com.ticketbox.data.remote.dto.RecurringCandidateItemDto
import com.ticketbox.data.remote.dto.DataQualitySummaryDto
import com.ticketbox.data.remote.dto.RuleApplicationBatchDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.remote.dto.RuleApplyPreviewItemDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.TagListItemDto
import com.ticketbox.data.remote.dto.TagMutationDto
import com.ticketbox.data.remote.dto.TagStatsDto
import com.ticketbox.data.remote.dto.TagUndoDto
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.domain.model.FrequentMerchant
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogMergeResult
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplicationRollback
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.RuleApplyPreviewItem
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.TagMutationResult
import com.ticketbox.domain.model.TagStats
import com.ticketbox.domain.model.TagUndoResult
import com.ticketbox.domain.model.normalizeExpenseCategory
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant

fun ExpenseDto.toDomain(): Expense {
    val imageAvailable = isImageAvailable
    val thumbnailAvailable = isThumbnailAvailable
    return Expense(
        id = id,
        publicId = requiredPublicId(),
        amountCents = amountCents,
        homeAmountCents = homeAmountCents ?: amountCents,
        homeCurrency = CurrencyCode.fromStorageKey(homeCurrency),
        originalCurrency = CurrencyCode.fromStorageKey(originalCurrency ?: originalCurrencyCode),
        originalAmount = originalAmount ?: minorToMajorText(originalAmountMinor, CurrencyCode.fromStorageKey(originalCurrency ?: originalCurrencyCode)),
        fxRate = resolvedFxRate,
        fxRateDate = resolvedFxRateDate,
        fxSource = resolvedFxSource,
        fxStatus = fxStatus.orEmpty(),
        originalCurrencyCode = CurrencyCode.fromStorageKey(originalCurrency ?: originalCurrencyCode),
        originalAmountMinor = originalAmountMinor,
        exchangeRateToCny = resolvedFxRate,
        exchangeRateDate = resolvedFxRateDate,
        exchangeRateSource = resolvedFxSource,
        merchant = merchant,
        category = normalizeExpenseCategory(category),
        note = note,
        source = source,
        imagePath = imagePath.takeIf { imageAvailable },
        thumbnailPath = thumbnailPath.takeIf { thumbnailAvailable },
        imageDeletedAt = imageDeletedAt,
        thumbnailDeletedAt = thumbnailDeletedAt,
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
        rowVersion = rowVersion,
        confirmedAt = confirmedAt,
        rejectedAt = rejectedAt,
    )
}

fun ExpenseDto.toEntity(ledgerId: String): ExpenseEntity = ExpenseEntity(
    ledgerId = ledgerId,
    serverId = id,
    publicId = requiredPublicId(),
    amountCents = amountCents,
    homeCurrencyCode = CurrencyCode.fromStorageKey(homeCurrency).storageKey,
    originalCurrencyCode = CurrencyCode.fromStorageKey(originalCurrency ?: originalCurrencyCode).storageKey,
    originalAmountMinor = originalAmountMinor ?: amountCents,
    exchangeRateToCny = resolvedFxRate,
    exchangeRateDate = resolvedFxRateDate,
    exchangeRateSource = resolvedFxSource,
    fxStatus = fxStatus.orEmpty(),
    merchant = merchant,
    category = normalizeExpenseCategory(category),
    note = note,
    source = source,
    thumbnailPath = thumbnailPath.takeIf { isThumbnailAvailable },
    imageDeletedAt = imageDeletedAt,
    thumbnailDeletedAt = thumbnailDeletedAt,
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
    confirmedAt = confirmedAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
)

private val ExpenseDto.resolvedFxRate: String?
    get() = fxRate ?: exchangeRateToCny

private val ExpenseDto.resolvedFxRateDate: String?
    get() = fxRateDate ?: exchangeRateDate

private val ExpenseDto.resolvedFxSource: String?
    get() = fxSource ?: exchangeRateSource

private val ExpenseDto.isImageAvailable: Boolean
    get() = imageDeletedAt == null

private val ExpenseDto.isThumbnailAvailable: Boolean
    get() = isImageAvailable && thumbnailDeletedAt == null

private fun ExpenseDto.requiredPublicId(): String {
    return publicId
        ?.trim()
        ?.takeIf { it.isNotBlank() }
        ?: throw RepositoryException("账本版本过旧，请重启电脑上的小票夹后再试。")
}

fun ExpenseEntity.toDomain(): Expense {
    val thumbnailAvailable = imageDeletedAt == null && thumbnailDeletedAt == null
    return Expense(
        // issue #65 slice 4: a not-yet-synced offline create (serverId == null)
        // gets a NEGATIVE stand-in derived from its local Room PK so id-keyed UI
        // (list keys / selection / action-gating) stays collision-free; once the
        // CreateExpense outbox row syncs, serverId is written back and this flips
        // to the real positive id. See [Expense.id] / [Expense.pendingSync].
        id = serverId ?: -id,
        publicId = publicId,
        amountCents = amountCents,
        homeAmountCents = amountCents,
        homeCurrency = CurrencyCode.fromStorageKey(homeCurrencyCode),
        originalCurrency = CurrencyCode.fromStorageKey(originalCurrencyCode),
        originalAmount = minorToMajorText(originalAmountMinor, CurrencyCode.fromStorageKey(originalCurrencyCode)),
        fxRate = exchangeRateToCny,
        fxRateDate = exchangeRateDate,
        fxSource = exchangeRateSource,
        fxStatus = fxStatus,
        originalCurrencyCode = CurrencyCode.fromStorageKey(originalCurrencyCode),
        originalAmountMinor = originalAmountMinor,
        exchangeRateToCny = exchangeRateToCny,
        exchangeRateDate = exchangeRateDate,
        exchangeRateSource = exchangeRateSource,
        merchant = merchant,
        category = normalizeExpenseCategory(category),
        note = note,
        source = source,
        imagePath = null,
        thumbnailPath = thumbnailPath.takeIf { thumbnailAvailable },
        imageDeletedAt = imageDeletedAt,
        thumbnailDeletedAt = thumbnailDeletedAt,
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
        updatedAt = updatedAt ?: createdAt,
        rowVersion = rowVersion,
        confirmedAt = confirmedAt,
        rejectedAt = null,
        clientRef = clientRef,
        pendingSync = serverId == null,
    )
}

/** Body builder for ``POST /api/expenses/manual``. Create semantics only —
 *  always submits the FX trio (currency / amount / spent_at) plus
 *  ``expense_time``; there is no baseline to diff against and the dedicated
 *  DTO has no OCC-token field by construction. [clientRef] (issue #65 slice 4)
 *  is the device-unique idempotency ref the offline-aware create path mints and
 *  reuses on outbox replay; the online quick-add path leaves it null. */
fun ExpenseDraft.toManualCreateRequest(clientRef: String? = null): ExpenseManualCreateRequestDto {
    val submittedOriginalMinor = originalAmountMinor ?: amountCents
    val submittedCurrency = originalCurrencyCode
        ?: if (submittedOriginalMinor != null) FxContract.HomeCurrency else null
    return ExpenseManualCreateRequestDto(
        originalCurrency = submittedCurrency?.storageKey,
        originalAmount = minorToMajorText(
            submittedOriginalMinor,
            submittedCurrency ?: FxContract.HomeCurrency,
        ),
        spentAt = expenseTime,
        merchant = merchant,
        category = normalizeExpenseCategory(category),
        note = note,
        expenseTime = expenseTime,
        tags = tags,
        valueScore = valueScore,
        regretScore = regretScore,
        clientRef = clientRef,
    )
}

/**
 * issue #65 slice 4: the optimistic local [ExpenseEntity] for an offline manual
 * create — written to Room immediately so the row shows in the confirmed list
 * (and survives an app restart) before its CreateExpense outbox row drains.
 *
 * ``serverId = null`` (no server id yet → drives [Expense.pendingSync]);
 * ``clientRef`` links it to the queued create + the server's
 * ``draft_idempotency_key``; ``publicId`` is a unique device-local sentinel that
 * the sync write-back replaces with the server's. Manual creates are confirmed
 * on the server immediately, so the row is cached as ``status = "confirmed"``
 * with ``source = 手动记账`` and ``rowVersion = 1`` (the server's create default).
 * Mirrors [toManualCreateRequest] for the FX-derived amount fields so the
 * optimistic row matches what the server will return.
 */
fun ExpenseDraft.toLocalCreateEntity(ledgerId: String, clientRef: String): ExpenseEntity {
    val submittedOriginalMinor = originalAmountMinor ?: amountCents
    val submittedCurrency = originalCurrencyCode ?: FxContract.HomeCurrency
    return ExpenseEntity(
        ledgerId = ledgerId,
        serverId = null,
        publicId = "local-$clientRef",
        amountCents = amountCents ?: submittedOriginalMinor,
        homeCurrencyCode = FxContract.HomeCurrency.storageKey,
        originalCurrencyCode = submittedCurrency.storageKey,
        originalAmountMinor = submittedOriginalMinor,
        exchangeRateToCny = null,
        exchangeRateDate = null,
        exchangeRateSource = null,
        fxStatus = FxContract.StatusReady,
        merchant = merchant.cleanOptional(),
        category = normalizeExpenseCategory(category),
        note = note.cleanOptional(),
        source = ExpenseSourceValues.MANUAL_ENTRY,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = tags.cleanOptional(),
        valueScore = valueScore,
        regretScore = regretScore,
        status = "confirmed",
        expenseTime = expenseTime,
        createdAt = Instant.now().toString(),
        confirmedAt = Instant.now().toString(),
        updatedAt = null,
        rowVersion = 1,
        clientRef = clientRef,
    )
}

fun ExpenseDraft.toRequest(baseline: Expense?): ExpenseUpdateRequest {
    val submittedOriginalMinor = originalAmountMinor ?: amountCents
    val submittedCurrency = originalCurrencyCode
        ?: if (submittedOriginalMinor != null) FxContract.HomeCurrency else null
    val submittedAmountText = minorToMajorText(
        submittedOriginalMinor,
        submittedCurrency ?: FxContract.HomeCurrency,
    )
    val isCreate = baseline == null
    val currencyChanged = baseline != null && submittedCurrency != baseline.originalCurrencyCode
    val amountChanged = baseline != null && submittedOriginalMinor != baseline.originalAmountMinor
    val timeChanged = baseline != null && expenseTime != baseline.expenseTime

    return ExpenseUpdateRequest(
        // ADR-0041: PATCH 必须携带 baseline.rowVersion 作为乐观锁 token。
        // manual create 已拆到 toManualCreateRequest()（专用 DTO 无 token 字段）；
        // baseline 参数不再有默认值，PATCH 调用点必须显式传。
        expectedRowVersion = baseline?.rowVersion,
        originalCurrency = if (isCreate || currencyChanged) submittedCurrency?.storageKey else null,
        originalAmount = if (isCreate || amountChanged) submittedAmountText else null,
        spentAt = if (isCreate || timeChanged) expenseTime else null,
        merchant = merchant,
        category = normalizeExpenseCategory(category),
        note = note,
        expenseTime = if (isCreate || timeChanged) expenseTime else null,
        tags = tags,
        valueScore = valueScore,
        regretScore = regretScore,
    )
}

fun NotificationDraft.toRequest(notificationKey: String? = null): NotificationDraftRequestDto = NotificationDraftRequestDto(
    source = source.apiValue,
    originalCurrency = FxContract.HomeCurrency.storageKey,
    originalAmount = minorToMajorText(amountCents, FxContract.HomeCurrency),
    spentAt = expenseTime,
    merchant = merchant?.trim()?.takeIf { it.isNotBlank() },
    category = normalizeExpenseCategory(category),
    expenseTime = expenseTime,
    notificationKey = notificationKey,
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
    bestValueExpenses = bestValueExpenses.map { it.toDomain() },
    mostRegrettedExpenses = mostRegrettedExpenses.map { it.toDomain() },
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
    rowVersion = rowVersion,
)

fun MerchantAliasDto.toDomain(): MerchantAlias = MerchantAlias(
    publicId = publicId,
    canonicalMerchant = canonicalMerchant,
    canonicalKey = canonicalKey,
    alias = alias,
    aliasKey = aliasKey,
    enabled = enabled,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
)

fun MerchantCatalogDto.toDomain(): MerchantCatalog = MerchantCatalog(
    publicId = publicId,
    displayName = displayName,
    merchantKey = merchantKey,
    status = status,
    mergedIntoPublicId = mergedIntoPublicId,
    usageCount = usageCount,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
    deletedAt = deletedAt,
)

fun MerchantCatalogMergeDto.toDomain(): MerchantCatalogMergeResult = MerchantCatalogMergeResult(
    source = source.toDomain(),
    target = target.toDomain(),
    createdAliasPublicId = createdAliasPublicId,
)

// ADR-0043 slice C — tag management DTO → domain.
fun TagListItemDto.toDomain(): ManagedTag = ManagedTag(
    publicId = publicId,
    name = name,
    usageCount = usageCount,
    rowVersion = rowVersion,
)

fun TagMutationDto.toDomain(): TagMutationResult = TagMutationResult(
    mutationPublicId = mutationPublicId,
    op = op,
    sourceTagPublicId = sourceTagPublicId,
    sourceTagRowVersion = sourceTagRowVersion,
    targetTagPublicId = targetTagPublicId,
    targetTagRowVersion = targetTagRowVersion,
    affectedExpenseCount = affectedExpenseCount,
)

fun TagUndoDto.toDomain(): TagUndoResult = TagUndoResult(
    restoredTagPublicId = restoredTagPublicId,
    restoredTagRowVersion = restoredTagRowVersion,
    applied = applied,
    skipped = skipped,
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

internal fun String?.cleanOptional(): String? = this?.trim()?.takeIf { it.isNotBlank() }

private fun minorToMajorText(amountMinor: Long?, currency: CurrencyCode): String? {
    if (amountMinor == null) return null
    return if (currency.noFractionDigits) {
        amountMinor.toString()
    } else {
        BigDecimal(amountMinor).divide(BigDecimal(100), 2, RoundingMode.HALF_UP).toPlainString()
    }
}
