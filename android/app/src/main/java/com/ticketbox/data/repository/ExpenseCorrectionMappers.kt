package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import com.ticketbox.data.remote.dto.ExpenseRevisionPageDto
import com.ticketbox.data.remote.dto.CorrectionOptionalInt
import com.ticketbox.data.remote.dto.CorrectionOptionalString
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.ExpenseRevisionPage

fun ExpenseRevisionDto.toDomain(): ExpenseRevision = ExpenseRevision(
    publicId = publicId,
    revisionNumber = revisionNumber,
    changeKind = changeKind,
    reason = reason,
    changedFields = changedFields,
    before = before,
    after = after,
    actorAccountName = actorAccountName,
    actorDeviceName = actorDeviceName,
    createdAt = createdAt,
)

fun ExpenseRevisionPageDto.toDomain(): ExpenseRevisionPage = ExpenseRevisionPage(
    items = items.map(ExpenseRevisionDto::toDomain),
    page = page,
    pageSize = pageSize,
    total = total,
)

fun ExpenseCorrectionDraft.toRequest(expectedRowVersion: Long): ExpenseCorrectionRequestDto {
    val cleanReason = reason.trim()
    if (cleanReason.isEmpty()) throw RepositoryException("请填写更正原因。")
    if (!hasMutationFields()) throw RepositoryException("没有需要保存的更正。")
    return ExpenseCorrectionRequestDto(
        expectedRowVersion = expectedRowVersion,
        reason = cleanReason,
        amountCents = amountCents,
        originalCurrencyCode = originalCurrencyCode?.storageKey,
        originalAmountMinor = originalAmountMinor,
        merchant = merchant,
        category = category,
        note = note,
        expenseTime = if (expenseTimeChanged) {
            CorrectionOptionalString.changed(expenseTime)
        } else {
            CorrectionOptionalString.unchanged()
        },
        tags = tags,
        valueScore = if (valueScoreChanged) {
            CorrectionOptionalInt.changed(valueScore)
        } else {
            CorrectionOptionalInt.unchanged()
        },
        regretScore = if (regretScoreChanged) {
            CorrectionOptionalInt.changed(regretScore)
        } else {
            CorrectionOptionalInt.unchanged()
        },
        items = items?.map { it.toRequest() },
        splits = splits?.map { it.toRequest() },
    )
}

private fun ExpenseCorrectionDraft.hasMutationFields(): Boolean =
    amountCents != null || originalCurrencyCode != null || originalAmountMinor != null ||
        merchant != null || category != null || note != null || expenseTimeChanged ||
        tags != null || valueScoreChanged || regretScoreChanged || items != null || splits != null

fun Expense.projectCorrection(draft: ExpenseCorrectionDraft): Expense =
    projectCorrectionMoney(draft).projectCorrectionDetails(draft)

private fun Expense.projectCorrectionMoney(draft: ExpenseCorrectionDraft): Expense = copy(
    amountCents = draft.amountCents ?: amountCents,
    homeAmountCents = draft.amountCents ?: homeAmountCents,
    originalCurrency = draft.originalCurrencyCode ?: originalCurrency,
    originalCurrencyCode = draft.originalCurrencyCode ?: originalCurrencyCode,
    originalCurrencyCodeRaw = draft.originalCurrencyCode?.storageKey ?: originalCurrencyCodeRaw,
    originalAmountMinor = draft.originalAmountMinor ?: originalAmountMinor,
)

private fun Expense.projectCorrectionDetails(draft: ExpenseCorrectionDraft): Expense = copy(
    merchant = draft.merchant ?: merchant,
    serverCategory = draft.category ?: serverCategory,
    category = draft.category ?: category,
    note = draft.note ?: note,
    expenseTime = if (draft.expenseTimeChanged) draft.expenseTime else expenseTime,
    tags = draft.tags ?: tags,
    valueScore = if (draft.valueScoreChanged) draft.valueScore else valueScore,
    regretScore = if (draft.regretScoreChanged) draft.regretScore else regretScore,
)

/**
 * Mirrors the advisor input owner: confirmed amount/original currency,
 * category, and captured time participate; merchant/note/tags/scores and
 * composite line metadata do not.
 */
fun ExpenseCorrectionDraft.changesAdvisorPayloadAgainst(baseline: Expense): Boolean =
    baseline.status == "confirmed" && (
        originalAmountMinor != null ||
            originalCurrencyCode != null ||
            category != null ||
            expenseTimeChanged
        )
