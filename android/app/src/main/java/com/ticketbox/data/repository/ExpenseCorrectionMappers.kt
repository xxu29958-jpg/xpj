package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitRequestDto
import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import com.ticketbox.data.remote.dto.ExpenseRevisionPageDto
import com.ticketbox.data.remote.dto.CorrectionOptionalInt
import com.ticketbox.data.remote.dto.CorrectionOptionalString
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.ExpenseRevisionPage
import com.ticketbox.domain.model.MONEY_MINOR_MAX
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
    splits != null && splits.size > 100 -> "一次更正最多保存 100 条分摊，请减少后再保存。"
    else -> correctionValueAdmissionError() ?: items?.firstNotNullOfOrNull { it.correctionAdmissionError() }
        ?: splits?.firstNotNullOfOrNull { it.correctionAdmissionError() }
}

private fun ExpenseItemRequestDto.correctionAdmissionError(): String? = when {
    name.codePointCount(0, name.length) !in 1..255 -> "请填写明细名称，最多 255 个字符。"
    kind !in setOf("product", "discount", "tax", "service_fee") -> "明细类型无法识别，请核对后再保存。"
    quantityText.exceedsCorrectionLimit(64) -> "明细数量说明最多 64 个字符。"
    category.exceedsCorrectionLimit(64) -> "明细分类名称最多 64 个字符。"
    rawText.exceedsCorrectionLimit(1000) -> "明细原文最多 1000 个字符。"
    confidence?.let { it !in 0.0..1.0 } == true -> "明细识别可信度超出范围，请核对后再保存。"
    unitPriceCents?.let { it !in 0L..MONEY_MINOR_MAX } == true -> "明细单价超出范围，请核对后再保存。"
    amountCents?.let { it !in if (kind == "discount") -MONEY_MINOR_MAX..0L else 0L..MONEY_MINOR_MAX } == true ->
        "明细金额超出该类型允许的范围，请核对后再保存。"
    else -> null
}

private fun ExpenseSplitRequestDto.correctionAdmissionError(): String? = when {
    memberId <= 0 -> "分摊成员无效，请核对当前成员后再保存。"
    amountCents <= 0 -> "每条分摊金额必须大于零，请核对后再保存。"
    amountCents > MONEY_MINOR_MAX -> "分摊金额超出范围，请核对后再保存。"
    note.exceedsCorrectionLimit(200) -> "分摊备注最多 200 个字符，请缩短后再保存。"
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

private fun ExpenseCorrectionRequestDto.correctionValueAdmissionError(): String? {
    val hasMutation = listOf(amountCents, originalCurrencyCode, originalAmountMinor, merchant, category,
        note, tags, items, splits).any { it != null } || expenseTime.changed || valueScore.changed || regretScore.changed
    return when {
        listOfNotNull(amountCents, originalAmountMinor).any { it !in 0L..MONEY_MINOR_MAX } ->
            "更正金额超出范围，请核对后再保存。"
        originalCurrencyCode?.let { it.codePointCount(0, it.length) != 3 } == true -> "币种代码须为 3 个字符。"
        listOf(valueScore, regretScore).any { it.changed && it.value?.let { score -> score !in 1..5 } == true } ->
            "评价分数须为 1 至 5，或明确清除评价。"
        !hasMutation -> "没有需要保存的更正。"
        else -> null
    }
}

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
