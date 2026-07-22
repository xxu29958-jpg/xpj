package com.ticketbox.domain.model

/**
 * Needs-review / ready-to-confirm judgment family for pending rows.
 *
 * These are pure domain predicates (no resources, no Compose) shared by the
 * inbox UI (filter chips, row primary action, queue counts) AND the
 * ViewModel bulk-confirm path — they live here so non-UI layers never import
 * `ui.screens.pending` (PR #230 round 7 layering fix). Behavior is identical
 * to the previous `PendingScreenModels.kt` home.
 */
internal enum class PendingPrimaryReviewAction {
    MissingAmount,
    DuplicateReview,
    QuickCategory,
    QuickMerchant,
    // Blocked on the exchange rate — the server confirm path 409s these rows
    // (exchange_rate_pending), so they are never a ready/confirm target.
    FxPending,
    Confirm,
}

internal data class PendingMerchantPresentation(
    val primaryText: String?,
) {
    val needsReview: Boolean = primaryText == null
}

internal fun pendingMerchantPresentation(expense: Expense): PendingMerchantPresentation {
    val primaryText = expense.merchant
        ?.trim()
        ?.takeIf(::isUsablePendingMerchantText)
    return PendingMerchantPresentation(primaryText = primaryText)
}

internal fun isUsablePendingMerchantText(value: String): Boolean {
    val meaningfulCharacterCount = value.count { it.isLetterOrDigit() }
    val merchantLetterCount = value.count { it.isLetter() }
    return meaningfulCharacterCount >= 2 &&
        merchantLetterCount >= 1 &&
        !PendingTimeNoise.matches(value) &&
        !PendingDateNoise.matches(value)
}

internal fun pendingPrimaryReviewAction(expense: Expense): PendingPrimaryReviewAction = when {
    expense.amountCents == null -> PendingPrimaryReviewAction.MissingAmount
    expense.duplicateStatus == DuplicateStatusValues.SUSPECTED -> PendingPrimaryReviewAction.DuplicateReview
    pendingNeedsCategory(expense) -> PendingPrimaryReviewAction.QuickCategory
    pendingMerchantPresentation(expense).needsReview -> PendingPrimaryReviewAction.QuickMerchant
    // fx 维度与后端 ready 口径/确认守卫一致（main 的 _ensure_expense_can_confirm
    // 对 fx-pending 行抛 409）——此类行不进 ready 集、不进批量确认。
    expense.fxStatus == FxContract.StatusPending -> PendingPrimaryReviewAction.FxPending
    else -> PendingPrimaryReviewAction.Confirm
}

// 读服务端原值（serverCategory），缺省回退到展示值：归一化成「其他」的
// blank/NULL 类目在后端 missing_category 计数里，这里必须同口径可见（PR #230）。
internal fun pendingNeedsCategory(expense: Expense): Boolean =
    isUncategorizedExpenseCategory(expense.serverCategory ?: expense.category)

private val PendingTimeNoise = Regex(
    pattern = """^\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?(?:\s*[AP]M)?$""",
    option = RegexOption.IGNORE_CASE,
)

private val PendingDateNoise = Regex(
    pattern = """^(?:\d{4}\s*[-/.年]\s*)?\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?(?:\s+周[一二三四五六日天])?(?:\s+\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?)?$""",
    option = RegexOption.IGNORE_CASE,
)
