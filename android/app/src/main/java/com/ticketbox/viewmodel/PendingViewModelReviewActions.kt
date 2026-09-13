package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.PendingPrimaryReviewAction
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.pendingPrimaryReviewAction
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * slice 3 M7 — PendingViewModel 的 Review 快速操作扩展。
 *
 * 与主 ViewModel 同文件包，使用 `internal` 字段访问。
 * 分类原因：保持 PendingViewModel.kt < 360 行（G2 闸门）。
 */

// ADR-0038 V6 fix — every sheet-opening path is "user moved to another
// action", so the prior 撤销 banner should disappear. Cheaper to gate here
// (the single sheet-opener surface) than to chase every individual write.
// Cancel timer + null undoableExpense via [dismissUndoable]; no-op when the
// banner is already absent.
//
// 从列表点开快补 sheet = 开启**新一轮**连续审阅：清空上一轮的跳过集合，
// 并按当前 sheet 字段算「还剩 N 条」。
fun PendingViewModel.openQuickCategory(expense: Expense) =
    openReviewSheet(PendingSheet.QuickCategory(expense))

fun PendingViewModel.openQuickMerchant(expense: Expense) =
    openReviewSheet(PendingSheet.QuickMerchant(expense))

fun PendingViewModel.openMissingAmount(expense: Expense) =
    openReviewSheet(PendingSheet.MissingAmount(expense))

private fun PendingViewModel.openReviewSheet(sheet: PendingSheet) {
    dismissUndoable()
    if (blockReadOnlyWrite()) return
    reviewSkippedIds.clear()
    _uiState.update { it.copy(activeSheet = sheet, message = null) }
    recomputeReviewRemaining()
}

fun PendingViewModel.openDuplicateAction(expense: Expense) {
    dismissUndoable()
    if (blockReadOnlyWrite()) return
    // 重复 sheet 不参与连续审阅推进；它打开时仍清掉上一轮残留的快补计数/跳过集。
    reviewSkippedIds.clear()
    _uiState.update { it.copy(activeSheet = PendingSheet.Duplicate(expense), message = null, reviewRemaining = 0) }
}

fun PendingViewModel.openBulkConfirm() {
    dismissUndoable()
    if (blockReadOnlyWrite()) return
    reviewSkippedIds.clear()
    _uiState.update { it.copy(activeSheet = PendingSheet.BulkConfirm, message = null, reviewRemaining = 0) }
}

fun PendingViewModel.closeSheet() {
    // 关闭 sheet 结束本轮连续审阅：清跳过集 + 计数归 0。
    reviewSkippedIds.clear()
    _uiState.update { it.copy(activeSheet = PendingSheet.None, reviewRemaining = 0) }
}

/**
 * 「跳过」当前快补票：不保存、不改后端状态，把当前票计入本轮跳过集，载入下一条
 * 仍缺同字段的票；队列耗尽则关闭 sheet 并给「已是最后一条」反馈。
 * 仅对快补 sheet（金额/商家/分类）生效，其它 sheet 无操作。
 */
fun PendingViewModel.skipReviewField() {
    if (blockReadOnlyWrite(closeSheet = true)) return
    val sheet = _uiState.value.activeSheet
    val field = reviewFieldOf(sheet) ?: return
    val currentId = reviewSheetExpenseId(sheet) ?: return
    // 当前票若仍在进行中（保存请求在途）则不跳，避免与推进竞态。
    if (currentId in _uiState.value.actionInProgressIds) return
    reviewSkippedIds.add(currentId)
    advanceReviewOrClose(
        field = field,
        handledId = currentId,
        exhaustedMessage = UiText.res(R.string.pending_review_queue_skip_last),
    )
}

fun PendingViewModel.saveQuickCategory(expenseId: Long, category: String) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    patchExpense(
        expenseId = expenseId,
        field = ReviewField.CATEGORY,
        draft = blankDraft().copy(category = category.trim()),
        failureMessageFallback = R.string.pending_review_category_save_failed,
    )
}

fun PendingViewModel.saveQuickMerchant(expenseId: Long, merchant: String) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    val cleaned = merchant.trim()
    if (cleaned.isEmpty()) {
        _uiState.update { it.copy(message = UiText.res(R.string.pending_review_merchant_blank)) }
        return
    }
    patchExpense(
        expenseId = expenseId,
        field = ReviewField.MERCHANT,
        draft = blankDraft().copy(merchant = cleaned),
        failureMessageFallback = R.string.pending_review_merchant_save_failed,
    )
}

fun PendingViewModel.saveAmountDraft(expenseId: Long, originalAmountMinor: Long) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    if (originalAmountMinor <= 0L) {
        _uiState.update { it.copy(message = UiText.res(R.string.pending_review_amount_not_positive)) }
        return
    }
    val expense = _uiState.value.items.firstOrNull { it.id == expenseId }
    if (originalCurrencyUnsupportedOf(expense)) return
    patchExpense(
        expenseId = expenseId,
        field = ReviewField.AMOUNT,
        draft = blankDraft().copy(
            originalCurrencyCode = expense?.originalCurrencyCode,
            originalAmountMinor = originalAmountMinor,
        ),
        failureMessageFallback = R.string.pending_review_amount_save_failed,
    )
}

fun PendingViewModel.saveAmountAndConfirm(expenseId: Long, originalAmountMinor: Long) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    if (originalAmountMinor <= 0L) {
        _uiState.update { it.copy(message = UiText.res(R.string.pending_review_amount_not_positive)) }
        return
    }
    val expense = _uiState.value.items.firstOrNull { it.id == expenseId } ?: return
    if (originalCurrencyUnsupportedOf(expense)) return
    val draft = blankDraft().copy(originalCurrencyCode = expense.originalCurrencyCode, originalAmountMinor = originalAmountMinor)
    submitPendingCommand(
        expense,
        R.string.pending_review_amount_save_failed,
        onAccepted = {
            reviewSkippedIds.add(expenseId)
            advanceReviewOrClose(ReviewField.AMOUNT, expenseId, UiText.res(R.string.expense_command_accepted))
        },
    ) { binding ->
        repository.saveAndConfirmExpense(binding, expense, draft)
    }
}

fun PendingViewModel.confirmReadyExpenses() {
    if (blockReadOnlyWrite(closeSheet = true)) return
    val state = _uiState.value
    if (state.bulkConfirm.running) return
    val ready = state.items.filter { pendingPrimaryReviewAction(it) == PendingPrimaryReviewAction.Confirm &&
        it.id !in commandRowsByExpense }
    if (ready.isEmpty()) {
        _uiState.update { it.copy(message = UiText.res(R.string.pending_review_bulk_none_ready)) }
        return
    }
    val binding = commandBinding() ?: return
    val ids = ready.map { it.id }.toSet()
    bulkCommandRows.clear()
    _uiState.update { it.copy(bulkConfirm = BulkConfirmRunState(total = ready.size, running = true),
        actionInProgressIds = it.actionInProgressIds + ids, message = null) }
    viewModelScope.launch {
        repository.confirmExpenses(binding, ready).onSuccess { accepted ->
            if (!holdsCommandBinding(binding)) {
                _uiState.update { it.copy(bulkConfirm = BulkConfirmRunState(),
                    actionInProgressIds = it.actionInProgressIds - ids) }
                return@onSuccess
            }
            bulkCommandRows.addAll(accepted.flatMap { it.rowIds })
            accepted.forEach { acceptExpenseCommand(it) }
            _uiState.update { it.copy(bulkConfirm = it.bulkConfirm.copy(running = false),
                activeSheet = PendingSheet.None, actionInProgressIds = it.actionInProgressIds - ids,
                message = UiText.res(R.string.expense_command_accepted)) }
            reconcileExpenseCommands()
        }.onFailure { error ->
            if (!holdsCommandBinding(binding)) {
                _uiState.update { it.copy(bulkConfirm = BulkConfirmRunState(),
                    actionInProgressIds = it.actionInProgressIds - ids) }
                return@onFailure
            }
            _uiState.update { it.copy(bulkConfirm = BulkConfirmRunState(total = ready.size, failed = ready.size),
                actionInProgressIds = it.actionInProgressIds - ids,
                message = error.toUiText(R.string.pending_msg_confirm_failed)) }
        }
    }
}

private fun blankDraft(): ExpenseDraft = ExpenseDraft(
    amountCents = null,
    merchant = null,
    category = null,
    note = null,
    expenseTime = null,
    tags = null,
    valueScore = null,
    regretScore = null,
)

/** 当前快补 sheet 携带的票 id；非快补 sheet 返回 null。 */
internal fun reviewSheetExpenseId(sheet: PendingSheet): Long? = when (sheet) {
    is PendingSheet.MissingAmount -> sheet.expense.id
    is PendingSheet.QuickMerchant -> sheet.expense.id
    is PendingSheet.QuickCategory -> sheet.expense.id
    is PendingSheet.Duplicate,
    is PendingSheet.BulkConfirm,
    is PendingSheet.None,
    -> null
}

/**
 * 连续审阅推进核心：当前票（[handledId]，保存成功或被跳过）处理完后，按列表口径
 * 找下一条仍缺 [field] 且本轮未跳过的票。
 *  - 有下一条 → 把 sheet 切到该票（同字段类型），不关闭，重算「还剩 N 条」；
 *    已有的成功/进度 message 保留。
 *  - 没有下一条（队列耗尽）→ 关闭 sheet、计数归 0，message 设为
 *    [exhaustedMessage]（保存路径 = 字段成功文案；跳过路径 = 「已是最后一条」）。
 *
 * 不读 / 不触网，纯状态机推进；下一条选择口径全在 [PendingReviewQueue]。
 */
private fun PendingViewModel.advanceReviewOrClose(
    field: ReviewField,
    handledId: Long,
    exhaustedMessage: UiText,
) {
    val state = _uiState.value
    val next = PendingReviewQueue.nextTarget(
        items = state.items,
        field = field,
        currentId = handledId,
        skippedIds = reviewSkippedIds,
    )
    if (next == null) {
        reviewSkippedIds.clear()
        _uiState.update {
            it.copy(
                activeSheet = PendingSheet.None,
                reviewRemaining = 0,
                message = exhaustedMessage,
            )
        }
        return
    }
    // 推进到下一条：清掉上一条的状态文案（成功提示），这样 sheet 内的状态行
    // 只会显示**失败**（保存失败时不推进、文案留在当前票）；成功推进保持安静。
    _uiState.update { it.copy(activeSheet = sheetForReviewField(field, next), message = null) }
    recomputeReviewRemaining()
}

private fun PendingViewModel.patchExpense(
    expenseId: Long,
    field: ReviewField,
    draft: ExpenseDraft,
    @StringRes failureMessageFallback: Int,
) {
    if (blockReadOnlyWrite(closeSheet = true)) return
    val baseline = _uiState.value.items.firstOrNull { it.id == expenseId } ?: return
    submitPendingCommand(
        baseline,
        failureMessageFallback,
        onAccepted = {
            reviewSkippedIds.add(expenseId)
            advanceReviewOrClose(field, expenseId, UiText.res(R.string.expense_command_accepted))
        },
    ) { binding ->
        repository.saveExpenseAllowingOffline(binding, expenseId, draft, baseline)
    }
}

/**
 * 按当前 [PendingUiState.activeSheet] 与 [PendingViewModel.reviewSkippedIds] 重算
 * 「还剩 N 条」。快补 sheet 没开 / 非补字段类 sheet 时归 0。放在 VM 这一层
 * （而非 Screen）因为它要读 reviewSkippedIds——属连续审阅业务态。
 */
internal fun PendingViewModel.recomputeReviewRemaining() {
    val state = _uiState.value
    val field = reviewFieldOf(state.activeSheet)
    val remaining = if (field == null) {
        0
    } else {
        PendingReviewQueue.remaining(state.items, field, reviewSkippedIds).size
    }
    if (remaining != state.reviewRemaining) {
        _uiState.update { it.copy(reviewRemaining = remaining) }
    }
}

/**
 * 当前 sheet 是否为支持连续审阅的快补类，及其对应字段。重复 / 批量 / 无
 * sheet 返回 null（不参与「保存并下一笔」推进）。
 */
internal fun reviewFieldOf(sheet: PendingSheet): ReviewField? = when (sheet) {
    is PendingSheet.MissingAmount -> ReviewField.AMOUNT
    is PendingSheet.QuickMerchant -> ReviewField.MERCHANT
    is PendingSheet.QuickCategory -> ReviewField.CATEGORY
    is PendingSheet.Duplicate,
    is PendingSheet.BulkConfirm,
    is PendingSheet.None,
    -> null
}

/** 为某字段类型 + 目标票构造对应快补 sheet（推进到下一条时复用）。 */
internal fun sheetForReviewField(field: ReviewField, expense: Expense): PendingSheet = when (field) {
    ReviewField.AMOUNT -> PendingSheet.MissingAmount(expense)
    ReviewField.MERCHANT -> PendingSheet.QuickMerchant(expense)
    ReviewField.CATEGORY -> PendingSheet.QuickCategory(expense)
}

/** R13-5：original 原码未知（支持集外）时金额承载写被禁 —— 返回 true 并亮明示文案
 *  （sheet 层同门已拦按钮，此为 VM 兜底防线）。 */
private fun PendingViewModel.originalCurrencyUnsupportedOf(expense: Expense?): Boolean {
    val raw = expense?.originalCurrencyCodeRaw
    val unsupported = !raw.isNullOrBlank() && CurrencyCode.fromStorageKeyOrNull(raw) == null
    if (unsupported) {
        _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_currency_unsupported)) }
    }
    return unsupported
}
