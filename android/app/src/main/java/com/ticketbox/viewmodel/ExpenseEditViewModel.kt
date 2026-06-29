package com.ticketbox.viewmodel

import android.util.Log
import com.ticketbox.BuildConfig
import com.ticketbox.R
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseEditActions
import com.ticketbox.data.repository.ExpenseStateOutcome
import com.ticketbox.data.repository.SaveOutcome
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.canCreateRepaymentDraft
import com.ticketbox.domain.model.canInitiateBillSplit
import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.math.abs
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * UI-editable working copy of one receipt line item. The amount is kept as the
 * raw text the user types (in yuan, magnitude only); the sign is derived from
 * [kind] on save (discount → negative, per ADR-0035) and parsed to cents.
 */
data class EditableItem(
    val name: String = "",
    val amountText: String = "",
    val kind: String = ExpenseItemKind.PRODUCT,
)

/**
 * ADR-0042 Slice E-1 UI-editable working copy of one member's bill-split share.
 * One row per ledger member: [included] is the checkbox, [amountText] the raw
 * yuan magnitude the user types (parsed to cents on save). [disabled] members
 * already on a split render greyed read-only so historical attribution isn't
 * dropped — they can't be toggled or edited but keep their existing amount.
 */
data class EditableSplit(
    val memberId: Long,
    val displayName: String,
    val included: Boolean,
    val amountText: String = "",
    val disabled: Boolean = false,
)

data class ExpenseEditUiState(
    val expense: Expense? = null,
    val expenseLoading: Boolean = true,
    val thumbnail: ProtectedImage? = null,
    val fullImage: ProtectedImage? = null,
    val categories: List<String> = DEFAULT_EXPENSE_CATEGORIES,
    val expenseItems: ExpenseItems? = null,
    val expenseSplits: ExpenseSplits? = null,
    val readOnly: Boolean = false,
    val imageLoading: Boolean = false,
    val itemsLoading: Boolean = false,
    val splitsLoading: Boolean = false,
    val ocrRunning: Boolean = false,
    val saving: Boolean = false,
    val itemEditorOpen: Boolean = false,
    val itemDrafts: List<EditableItem> = emptyList(),
    val itemsSaving: Boolean = false,
    val itemsMessage: UiText? = null,
    val splitEditorOpen: Boolean = false,
    val splitDrafts: List<EditableSplit> = emptyList(),
    val splitMembersLoading: Boolean = false,
    val splitsSaving: Boolean = false,
    val splitsMessage: UiText? = null,
    // ADR-0029 拆账发起（批 13）。billSplitSent 已按本票 senderExpenseId 过滤；
    // inviteSheetOpen 控制发起 sheet；inviteMembers 是可选收件人（已剔自己/停用）；
    // inviteSelectedMemberId/inviteAmountText 是 sheet 表单态；inviteSending 是发送中。
    val billSplitSent: List<BillSplitSent> = emptyList(),
    val billSplitLoading: Boolean = false,
    val billSplitMessage: UiText? = null,
    val billSplitInviteSheetOpen: Boolean = false,
    val billSplitInviteMembers: List<FamilyMember> = emptyList(),
    val billSplitInviteMembersLoading: Boolean = false,
    val billSplitInviteSelectedMemberId: Long? = null,
    val billSplitInviteAmountText: String = "",
    val billSplitInviteSending: Boolean = false,
    val billSplitInviteMessage: UiText? = null,
    val recognizeTextDialogOpen: Boolean = false,
    val repaymentDraftCreating: Boolean = false,
    val openRepaymentDrafts: Boolean = false,
    val message: UiText? = null,
    val done: Boolean = false,
)

/**
 * 主编辑面：加载（expense / categories / 图片 / items / splits）+ 保存 /
 * 确认 / 拒绝 / OCR 重试 / 粘贴识别 / 非重复标记。items 编辑器域在
 * [ExpenseEditViewModelItemsEditor.kt]、splits 编辑器域在
 * [ExpenseEditViewModelSplitsEditor.kt]（架构债 #5 拆分，同包扩展函数，
 * PendingViewModelReviewActions 先例模式）。
 */
class ExpenseEditViewModel(
    private val expenseId: Long,
    // 架构债 #5: narrow action interface (PendingReviewActions pattern) so unit
    // tests can fake the repository facade; `internal` so the items / splits
    // editor extension files (same package) reach it.
    internal val repository: ExpenseEditActions,
) : ViewModel() {
    private companion object {
        const val IMAGE_LOG_TAG = "TicketboxImage"
    }

    internal val _uiState = MutableStateFlow(
        ExpenseEditUiState(readOnly = !repository.canModifyLedger()),
    )
    val uiState: StateFlow<ExpenseEditUiState> = _uiState.asStateFlow()

    init {
        loadExpense()
        loadCategories()
        // issue #65 slice 5: a not-yet-synced offline create (negative local id)
        // has no server-side image / line items / splits yet — skip those loads so
        // they don't 404 and surface spurious "load failed" messages on the page.
        if (expenseId > 0) {
            loadThumbnail()
            loadExpenseItems()
            loadExpenseSplits()
        }
    }

    fun retryLoadExpense() {
        loadExpense()
    }

    private fun loadExpense() {
        viewModelScope.launch {
            _uiState.update { it.copy(expenseLoading = true, message = null) }
            // issue #65 slice 5: a not-yet-synced offline create has a NEGATIVE
            // local id the server can't resolve — load it from the local cache.
            val loaded = if (expenseId < 0) {
                repository.fetchExpenseFromLocalCache(expenseId)
            } else {
                repository.fetchExpense(expenseId)
            }
            loaded
                .onSuccess { expense ->
                    _uiState.update {
                        it.copy(
                            expense = expense,
                            expenseLoading = false,
                            message = null,
                        )
                    }
                    // 批 13：仅已确认/有金额/非收到拆账/可写的票才拉本票已发邀请，
                    // 给「找家人分摊」卡填列表（pending/received 票不发无谓请求）。
                    if (expense.canInitiateBillSplit(_uiState.value.readOnly)) {
                        loadBillSplitSent()
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            expenseLoading = false,
                            message = error.toUiText(R.string.expense_edit_load_failed),
                        )
                    }
                }
        }
    }

    private fun loadCategories() {
        viewModelScope.launch {
            repository.categories()
                .onSuccess { categories -> _uiState.update { it.copy(categories = categories) } }
                .onFailure { _uiState.update { it.copy(categories = DEFAULT_EXPENSE_CATEGORIES) } }
        }
    }

    private fun loadThumbnail() {
        viewModelScope.launch {
            _uiState.update { it.copy(imageLoading = true) }
            repository.fetchThumbnail(expenseId)
                .onSuccess { image -> _uiState.update { it.copy(thumbnail = image, imageLoading = false) } }
                .onFailure { thumbnailError ->
                    if (BuildConfig.DEBUG) {
                        Log.w(IMAGE_LOG_TAG, "Thumbnail preview failed for expense=$expenseId: ${thumbnailError.message}")
                    }
                    repository.fetchImage(expenseId)
                        .onSuccess { image ->
                            _uiState.update { it.copy(fullImage = image, imageLoading = false) }
                        }
                        .onFailure { imageError ->
                            if (BuildConfig.DEBUG) {
                                Log.w(IMAGE_LOG_TAG, "Full image fallback failed for expense=$expenseId: ${imageError.message}")
                            }
                            _uiState.update { it.copy(imageLoading = false) }
                        }
                }
        }
    }

    private fun loadExpenseItems() {
        viewModelScope.launch {
            _uiState.update { it.copy(itemsLoading = true, itemsMessage = null) }
            repository.fetchExpenseItems(expenseId)
                .onSuccess { items ->
                    _uiState.update { it.copy(expenseItems = items, itemsLoading = false) }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            itemsLoading = false,
                            itemsMessage = error.toUiText(R.string.expense_edit_items_load_failed),
                        )
                    }
                }
        }
    }

    private fun loadExpenseSplits() {
        viewModelScope.launch {
            _uiState.update { it.copy(splitsLoading = true, splitsMessage = null) }
            repository.fetchExpenseSplits(expenseId)
                .onSuccess { splits ->
                    _uiState.update { it.copy(expenseSplits = splits, splitsLoading = false) }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            splitsLoading = false,
                            splitsMessage = error.toUiText(R.string.expense_edit_splits_load_failed),
                        )
                    }
                }
        }
    }

    fun loadFullImage() {
        viewModelScope.launch {
            _uiState.update { it.copy(imageLoading = true, message = null) }
            repository.fetchImage(expenseId)
                .onSuccess { image -> _uiState.update { it.copy(fullImage = image, imageLoading = false) } }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            imageLoading = false,
                            message = error.toUiText(R.string.expense_edit_image_open_failed),
                        )
                    }
                }
        }
    }

    fun save(draft: ExpenseDraft) {
        if (blockReadOnlyWrite()) return
        viewModelScope.launch {
            val baseline = _uiState.value.expense
            _uiState.update { it.copy(saving = true, message = null) }
            // ADR-0038 PR-2g.3 round-8 P2: this is the only call
            // site that doesn't chain on ``saved.updatedAt``. The
            // chained ``confirm()`` flow below uses ``updateExpense``
            // (direct only — fails on IOException so the chain
            // aborts safely). Here we use the offline-aware
            // ``saveExpenseAllowingOffline`` and branch on the
            // sealed result so the UI tells the user whether the
            // save was confirmed or just queued.
            if (baseline == null) {
                // No baseline → no optimistic-concurrency token.
                // saveExpenseAllowingOffline requires non-null
                // baseline; fall back to the direct path which
                // will surface whatever error appropriate.
                repository.updateExpense(expenseId, draft, baseline = null)
                    .onSuccess { expense ->
                        _uiState.update { it.copy(expense = expense, saving = false, message = UiText.res(R.string.expense_edit_save_success), done = true) }
                    }
                    .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.toUiText(R.string.expense_edit_save_failed)) } }
                return@launch
            }
            repository.saveExpenseAllowingOffline(expenseId, draft, baseline)
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        is SaveOutcome.Synced -> UiText.res(R.string.expense_edit_save_success)
                        // codex round-8 P2: queued state is honestly
                        // surfaced to the user — they typed an edit
                        // while offline, the worker will sync when
                        // network returns. PR-2g.5 banner adds the
                        // "你有 N 笔待同步" pill globally; this
                        // message is the per-save signal.
                        is SaveOutcome.Queued -> UiText.res(R.string.expense_edit_save_offline_queued)
                    }
                    _uiState.update {
                        it.copy(
                            expense = outcome.expense,
                            saving = false,
                            message = message,
                            done = true,
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.toUiText(R.string.expense_edit_save_failed)) } }
        }
    }

    fun confirm(draft: ExpenseDraft) {
        if (blockReadOnlyWrite()) return
        if (draft.amountCents == null && draft.originalAmountMinor == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_amount_required)) }
            return
        }
        val baseline = _uiState.value.expense
        if (baseline == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            // ADR-0042: route the edit-page save+confirm through the offline-aware
            // path (like the pending-list confirm) instead of the direct
            // updateExpense+confirmExpense chain, which failed entirely offline and
            // lost the user's confirm intent. Offline, BOTH mutations queue; the
            // outbox serialises same-target (PatchExpense before ConfirmExpense) and
            // cascades the post-save row_version onto the queued confirm, so the
            // optimistic (pre-save) token on the queued confirm is corrected on
            // replay. Online, the save Syncs (server token) and the confirm runs
            // direct against it — same result as before.
            repository.saveExpenseAllowingOffline(expenseId, draft, baseline)
                .onSuccess { saveOutcome ->
                    repository.confirmExpenseAllowingOffline(saveOutcome.expense)
                        .onSuccess { confirmOutcome ->
                            // Queued = the confirm sits behind the queued save in the
                            // outbox (per-target FIFO; the repository diverts the
                            // confirm to the queue whenever the save queued first) —
                            // surface the offline hint like reject/save do.
                            val message = when (confirmOutcome) {
                                is ExpenseStateOutcome.Synced -> null
                                is ExpenseStateOutcome.Queued -> UiText.res(R.string.expense_edit_confirm_offline_queued)
                            }
                            _uiState.update { state ->
                                state.copy(expense = confirmOutcome.expense, saving = false, message = message, done = true)
                            }
                        }
                        .onFailure { error ->
                            // Keep the post-save expense as the page baseline. After a
                            // Synced save it carries the server's bumped row_version
                            // (retrying with the stale pre-save token would always
                            // 409); after a Queued save it's the optimistic projection
                            // whose pre-save token is exactly what the queued PATCH
                            // will replay — and any follow-up mutate now queues behind
                            // it via the per-target FIFO guard.
                            _uiState.update { state -> state.copy(expense = saveOutcome.expense, saving = false, message = error.toUiText(R.string.expense_edit_confirm_failed)) }
                        }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.toUiText(R.string.expense_edit_save_failed)) } }
        }
    }

    fun reject() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            repository.rejectExpenseAllowingOffline(expense)
                .onSuccess { outcome ->
                    // Synced keeps the silent done→navigate-back behaviour;
                    // Queued surfaces the offline hint (mirrors save).
                    val message = when (outcome) {
                        is ExpenseStateOutcome.Synced -> null
                        is ExpenseStateOutcome.Queued -> UiText.res(R.string.expense_edit_reject_offline_queued)
                    }
                    _uiState.update { it.copy(saving = false, message = message, done = true) }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.toUiText(R.string.expense_edit_reject_failed)) } }
        }
    }

    fun retryOcr() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(ocrRunning = true, message = null) }
            repository.retryOcrAllowingOffline(expense)
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        is ExpenseStateOutcome.Synced -> UiText.res(R.string.expense_edit_ocr_retried)
                        is ExpenseStateOutcome.Queued -> UiText.res(R.string.expense_edit_ocr_retry_offline_queued)
                    }
                    _uiState.update { it.copy(expense = outcome.expense, ocrRunning = false, message = message) }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(ocrRunning = false, message = error.toUiText(R.string.expense_edit_recognize_failed)) }
                }
        }
    }

    /** Open / close the "粘贴文字识别" input dialog. Gated on read-only at the
     *  UI layer (the affordance is hidden), but the open call also no-ops if the
     *  expense hasn't loaded so the dialog never opens on a half-loaded page. */
    fun openRecognizeTextDialog() {
        if (_uiState.value.expense == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded)) }
            return
        }
        _uiState.update { it.copy(recognizeTextDialogOpen = true) }
    }

    fun closeRecognizeTextDialog() {
        _uiState.update { it.copy(recognizeTextDialogOpen = false) }
    }

    /**
     * ADR-0042 Slice E-2: submit pasted receipt text for server-side parsing.
     * Modeled on [retryOcr] (Synced/Queued ExpenseStateOutcome), but body-carrying
     * — the pasted [rawText] travels to the server, which parses it into the
     * empty draft fields (DISTINCT from retryOcr, which re-runs the OCR provider
     * on the stored image). The parsed result only fills EMPTY fields — that's
     * enforced server-side (recognize is pending-only + the OCR-apply owns only
     * draft fields), so the copy is honest about it and there's no client-side
     * overwrite logic.
     */
    fun recognizeText(rawText: String) {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded)) }
            return
        }
        val text = rawText.trim()
        if (text.isBlank()) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_recognize_text_required)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(ocrRunning = true, recognizeTextDialogOpen = false, message = null) }
            repository.recognizeTextAllowingOffline(expense, text)
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        // Server parsed the text and returned the refreshed expense;
                        // the Screen re-derives its field state from it (parsed
                        // result already filled the empty fields server-side).
                        is ExpenseStateOutcome.Synced -> UiText.res(R.string.expense_edit_recognize_done)
                        is ExpenseStateOutcome.Queued -> UiText.res(R.string.expense_edit_recognize_offline_queued)
                    }
                    _uiState.update { it.copy(expense = outcome.expense, ocrRunning = false, message = message) }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(ocrRunning = false, message = error.toUiText(R.string.expense_edit_recognize_failed)) }
                }
        }
    }

    fun markNotDuplicate() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded)) }
            return
        }
        viewModelScope.launch {
            repository.markNotDuplicateAllowingOffline(expense)
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        is ExpenseStateOutcome.Synced -> UiText.res(R.string.expense_edit_keep_duplicate_success)
                        is ExpenseStateOutcome.Queued -> UiText.res(R.string.expense_edit_keep_duplicate_offline_queued)
                    }
                    _uiState.update { it.copy(expense = outcome.expense, message = message) }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.expense_edit_keep_duplicate_failed)) } }
        }
    }

    fun createRepaymentDraftFromExpense() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded)) }
            return
        }
        if (!expense.canCreateRepaymentDraft(_uiState.value.readOnly)) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_edit_repayment_draft_unavailable)) }
            return
        }
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    repaymentDraftCreating = true,
                    openRepaymentDrafts = false,
                    message = null,
                )
            }
            repository.createRepaymentDraftFromExpense(expense)
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            repaymentDraftCreating = false,
                            openRepaymentDrafts = true,
                            message = UiText.res(R.string.expense_edit_repayment_draft_created),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            repaymentDraftCreating = false,
                            message = error.toUiText(R.string.expense_edit_repayment_draft_failed),
                        )
                    }
                }
        }
    }

    fun consumeDone(): Boolean {
        val wasDone = _uiState.value.done
        if (wasDone) {
            _uiState.update { it.copy(done = false) }
        }
        return wasDone
    }

    fun consumeOpenRepaymentDrafts(): Boolean {
        val shouldOpen = _uiState.value.openRepaymentDrafts
        if (shouldOpen) {
            _uiState.update { it.copy(openRepaymentDrafts = false) }
        }
        return shouldOpen
    }

    private fun blockReadOnlyWrite(): Boolean {
        if (repository.canModifyLedger()) {
            _uiState.update { it.copy(readOnly = false) }
            return false
        }
        _uiState.update {
            it.copy(
                readOnly = true,
                saving = false,
                ocrRunning = false,
                repaymentDraftCreating = false,
                message = UiText.res(R.string.common_readonly_ledger),
            )
        }
        return true
    }

    /** Yuan-text rendering shared by the items / splits editor extension files. */
    internal fun centsToYuanText(cents: Long?): String {
        if (cents == null) return ""
        return BigDecimal(abs(cents)).divide(BigDecimal(100), 2, RoundingMode.HALF_UP).toPlainString()
    }
}
