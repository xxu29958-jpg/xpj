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
import java.util.Locale

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
    snapshotRevision = snapshotRevision,
)

fun ExpenseCorrectionDraft.toRequest(expectedRowVersion: Long): ExpenseCorrectionRequestDto {
    val cleanReason = reason.trim { it.isCorrectionWhitespace() }
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
    ).also { request ->
        request.correctionAdmissionError()?.let { throw RepositoryException(it) }
        if (!hasMutationFields()) throw RepositoryException("没有需要保存的更正。")
    }
}

/** Pure request admission shared by first save and original-command replay; never rewrites a saved request. */
internal fun ExpenseCorrectionRequestDto.correctionAdmissionError(): String? = when {
    reason.all { it.isCorrectionWhitespace() } -> "请填写更正原因。"
    reason.exceedsCorrectionLimit(500) -> "更正原因最多 500 个字符，请缩短后再保存。"
    merchant.exceedsCorrectionLimit(255) -> "商家名称最多 255 个字符，请缩短后再保存。"
    category.exceedsCorrectionLimit(64) -> "分类名称最多 64 个字符，请缩短后再保存。"
    tags.exceedsCorrectionLimit(500) -> "标签合计最多 500 个字符，请缩短后再保存。"
    tags?.hasOversizedCorrectionTag() == true -> "单个标签标准化后最多 64 个字符，请缩短后再保存。"
    items != null && items.size > 200 -> "一次更正最多保存 200 条明细，请减少后再保存。"
    items?.any { it.name.exceedsCorrectionLimit(255) } == true -> "明细名称最多 255 个字符，请缩短后再保存。"
    splits != null && splits.size > 100 -> "一次更正最多保存 100 条分摊，请减少后再保存。"
    splits?.any { it.amountCents <= 0 } == true -> "每条分摊金额必须大于零，请核对后再保存。"
    else -> null
}

private fun String?.exceedsCorrectionLimit(limit: Int): Boolean =
    this != null && codePointCount(0, length) > limit

// Python str.strip / re \s include NEXT LINE as well as Unicode whitespace.
private fun Char.isCorrectionWhitespace(): Boolean = isWhitespace() || this == '\u0085'

private fun String.hasOversizedCorrectionTag(): Boolean = split(',', '，', ';', '；', '\n').any { raw ->
    val name = buildString {
        var separator = false
        for (character in raw) {
            if (character.isCorrectionWhitespace()) {
                separator = isNotEmpty()
            } else {
                if (separator) append(' ')
                append(character)
                separator = false
            }
        }
    }
    // Inspect expansion width only. The server owns canonical tag keys and deduplication;
    // neither this temporary name nor its case-converted text replaces the original request.
    name.exceedsCorrectionLimit(64) ||
        name.lowercase(Locale.ROOT).uppercase(Locale.ROOT).lowercase(Locale.ROOT).exceedsCorrectionLimit(64)
}

private fun ExpenseCorrectionDraft.hasMutationFields(): Boolean =
    amountCents != null || originalCurrencyCode != null || originalAmountMinor != null ||
        merchant != null || category != null || note != null || expenseTimeChanged ||
        tags != null || valueScoreChanged || regretScoreChanged || items != null || splits != null

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
