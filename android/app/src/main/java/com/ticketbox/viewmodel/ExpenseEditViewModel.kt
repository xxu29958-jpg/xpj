package com.ticketbox.viewmodel

import android.util.Log
import com.ticketbox.BuildConfig
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.ExpenseStateOutcome
import com.ticketbox.data.repository.SaveOutcome
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

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
    val itemsMessage: String? = null,
    val splitsMessage: String? = null,
    val message: String? = null,
    val done: Boolean = false,
)

class ExpenseEditViewModel(
    private val expenseId: Long,
    private val repository: ExpenseRepository,
) : ViewModel() {
    private companion object {
        const val IMAGE_LOG_TAG = "TicketboxImage"
    }

    private val _uiState = MutableStateFlow(
        ExpenseEditUiState(readOnly = !repository.canModifyLedger()),
    )
    val uiState: StateFlow<ExpenseEditUiState> = _uiState.asStateFlow()

    init {
        loadExpense()
        loadCategories()
        loadThumbnail()
        loadExpenseItems()
        loadExpenseSplits()
    }

    fun retryLoadExpense() {
        loadExpense()
    }

    private fun loadExpense() {
        viewModelScope.launch {
            _uiState.update { it.copy(expenseLoading = true, message = null) }
            repository.fetchExpense(expenseId)
                .onSuccess { expense ->
                    _uiState.update {
                        it.copy(
                            expense = expense,
                            expenseLoading = false,
                            message = null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            expenseLoading = false,
                            message = error.message ?: "账单暂时加载失败，请稍后再试。",
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
                            itemsMessage = error.message ?: "小票明细暂时加载失败。",
                        )
                    }
                }
        }
    }

    fun acknowledgeItemsMismatch() {
        // ADR-0038 PR-2e: pass the expense's last-seen ``updatedAt`` as the
        // optimistic-concurrency token. If the expense hasn't loaded yet (no
        // baseline snapshot to compare against), bail with the same items
        // message UX the network paths use.
        val token = _uiState.value.expense?.updatedAt
        if (token == null) {
            _uiState.update {
                it.copy(itemsMessage = "账单还在加载，请稍后再点。")
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(itemsLoading = true, itemsMessage = null) }
            repository.acknowledgeExpenseItemsMismatch(expenseId, token)
                .onSuccess { items ->
                    // ADR-0038 PR-2e: ack bumps the parent expense's
                    // ``updated_at`` server-side. Refresh ``_uiState.expense``
                    // so subsequent same-page mutations (PATCH / confirm /
                    // reject / OCR retry) pick up the new token instead of
                    // racing themselves with a now-stale one.
                    //
                    // Refresh inline INSTEAD of calling ``loadExpense()``:
                    // ``loadExpense`` flips ``message`` to ``null`` at the
                    // start of its coroutine, which would erase the success
                    // banner we set below. We only need the new
                    // ``updatedAt`` here, so a surgical update keeps the
                    // success message visible.
                    val refreshedExpense = repository.fetchExpense(expenseId).getOrNull()
                    _uiState.update {
                        it.copy(
                            expense = refreshedExpense ?: it.expense,
                            expenseItems = items,
                            itemsLoading = false,
                            message = "已确认原小票如此。",
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            itemsLoading = false,
                            itemsMessage = error.message ?: "确认差异失败，请稍后重试。",
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
                            splitsMessage = error.message ?: "家庭拆账暂时加载失败。",
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
                            message = error.message ?: "截图暂时打不开，请稍后再试。",
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
                        _uiState.update { it.copy(expense = expense, saving = false, message = "已保存", done = true) }
                    }
                    .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "没有保存成功，请稍后再试。") } }
                return@launch
            }
            repository.saveExpenseAllowingOffline(expenseId, draft, baseline)
                .onSuccess { outcome ->
                    val message = when (outcome) {
                        is SaveOutcome.Synced -> "已保存"
                        // codex round-8 P2: queued state is honestly
                        // surfaced to the user — they typed an edit
                        // while offline, the worker will sync when
                        // network returns. PR-2g.5 banner adds the
                        // "你有 N 笔待同步" pill globally; this
                        // message is the per-save signal.
                        is SaveOutcome.Queued -> "已离线保存，联网后同步"
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
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "没有保存成功，请稍后再试。") } }
        }
    }

    fun confirm(draft: ExpenseDraft) {
        if (blockReadOnlyWrite()) return
        if (draft.amountCents == null && draft.originalAmountMinor == null) {
            _uiState.update { it.copy(message = "请先填写金额。") }
            return
        }
        viewModelScope.launch {
            val baseline = _uiState.value.expense
            _uiState.update { it.copy(saving = true, message = null) }
            repository.updateExpense(expenseId, draft, baseline)
                .onSuccess { saved ->
                    // ADR-0038 PR-2b: post-PATCH ``saved.updatedAt`` is the
                    // fresh optimistic-concurrency token confirm must use.
                    repository.confirmExpense(expenseId, saved.updatedAt)
                        .onSuccess { confirmed ->
                            _uiState.update { state -> state.copy(expense = confirmed, saving = false, done = true) }
                        }
                        .onFailure { error ->
                            _uiState.update { state -> state.copy(saving = false, message = error.message ?: "没有确认成功，请稍后再试。") }
                        }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "没有保存成功，请稍后再试。") } }
        }
    }

    fun reject() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update { it.copy(message = "页面尚未加载完成，请稍后再试。") }
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
                        is ExpenseStateOutcome.Queued -> "已离线删除，联网后同步"
                    }
                    _uiState.update { it.copy(saving = false, message = message, done = true) }
                }
                .onFailure { error -> _uiState.update { it.copy(saving = false, message = error.message ?: "没有删除成功，请稍后再试。") } }
        }
    }

    fun retryOcr() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update { it.copy(message = "页面尚未加载完成，请稍后再试。") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(ocrRunning = true, message = null) }
            repository.retryOcr(expenseId, expense.updatedAt)
                .onSuccess { expense ->
                    _uiState.update { it.copy(expense = expense, ocrRunning = false, message = "识别已重试") }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(ocrRunning = false, message = error.message ?: "没有识别成功，请稍后再试。") }
                }
        }
    }

    fun markNotDuplicate() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update { it.copy(message = "页面尚未加载完成，请稍后再试。") }
            return
        }
        viewModelScope.launch {
            repository.markNotDuplicate(expenseId, expense.updatedAt)
                .onSuccess { updated ->
                    _uiState.update { it.copy(expense = updated, message = "已保留这条账单") }
                }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "暂时没处理成功，请稍后再试。") } }
        }
    }

    fun consumeDone(): Boolean {
        val wasDone = _uiState.value.done
        if (wasDone) {
            _uiState.update { it.copy(done = false) }
        }
        return wasDone
    }

    private fun blockReadOnlyWrite(): Boolean {
        if (repository.canModifyLedger()) {
            _uiState.update { it.copy(readOnly = false) }
            return false
        }
        _uiState.update { it.copy(readOnly = true, saving = false, ocrRunning = false, message = READ_ONLY_LEDGER_MESSAGE) }
        return true
    }
}
