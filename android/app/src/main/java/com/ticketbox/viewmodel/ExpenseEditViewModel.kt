package com.ticketbox.viewmodel

import android.util.Log
import com.ticketbox.BuildConfig
import com.ticketbox.R
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseEditActions
import com.ticketbox.data.repository.ExpenseStateOutcome
import com.ticketbox.data.repository.SaveOutcome
import com.ticketbox.data.repository.changesAdvisorPayloadAgainst
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.formatMinorAmountInput
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
    /** Hidden baseline fields that must survive a replace-style save. */
    val quantityText: String? = null,
    val unitPriceCents: Long? = null,
    val category: String? = null,
    val rawText: String? = null,
    val confidence: Double? = null,
    /** Original signed minor value, used to preserve unsupported-currency rows. */
    val baselineAmountCents: Long? = null,
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
    /** Hidden baseline attribution note preserved when only the amount changes. */
    val note: String? = null,
    /** Original minor value, used to preserve unsupported-currency rows. */
    val baselineAmountCents: Long? = null,
)

enum class ExpenseDetailDataLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

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
    val itemsLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Unknown,
    val splitsLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Unknown,
    val ocrRunning: Boolean = false,
    val saving: Boolean = false,
    val itemEditorOpen: Boolean = false,
    val itemDrafts: List<EditableItem> = emptyList(),
    val itemsSaving: Boolean = false,
    val itemsMessage: UiText? = null,
    val itemsMessageTone: MessageTone = MessageTone.Neutral,
    val splitEditorOpen: Boolean = false,
    val splitDrafts: List<EditableSplit> = emptyList(),
    val splitMembersLoading: Boolean = false,
    val splitsSaving: Boolean = false,
    val splitsMessage: UiText? = null,
    val splitsMessageTone: MessageTone = MessageTone.Neutral,
    val recognizeTextDialogOpen: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val done: Boolean = false,

    /** Set alongside [done]: whether the completed save changed fields the
     *  budget advisor's payload aggregates (amount / currency / category /
     *  captured date-time) — or changed confirmed-set membership
     *  (confirm / reject). Consumed by the route to decide advice-cache
     *  invalidation; note/tag/merchant-only edits stay false. */
    val doneAdviceInputsChanged: Boolean = false,
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
    }

    fun retryLoadExpense() {
        loadExpense()
    }

    private fun loadExpense() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(expenseLoading = true, message = null, messageTone = MessageTone.Neutral)
            }
            // issue #65 slice 5: a not-yet-synced offline create has a NEGATIVE
            // local id the server can't resolve — load it from the local cache.
            val loaded = if (expenseId < 0) {
                repository.fetchExpenseFromLocalCache(expenseId)
            } else {
                repository.fetchExpense(expenseId).let { remote ->
                    if (remote.isSuccess) remote else repository.fetchExpenseFromLocalCache(expenseId)
                }
            }
            loaded
                .onSuccess { expense ->
                    _uiState.update {
                        it.copy(
                            expense = expense,
                            expenseLoading = false,
                            message = null,
                            messageTone = MessageTone.Neutral,
                        )
                    }
                    // A1 owner retirement: this VM may identify the status for routing,
                    // but the confirmed fact owner alone loads category/media/items/splits
                    // and bill-split projections. Starting those reads here creates a hidden
                    // second page state behind ExpenseFactRoute.
                    if (expense.status != "confirmed") {
                        loadLegacyEditorDependencies(expense)
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            expenseLoading = false,
                            message = error.toUiText(R.string.expense_edit_load_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    private fun loadLegacyEditorDependencies(expense: Expense) {
        loadCategories()
        // issue #65 slice 5: a not-yet-synced offline create (negative local id)
        // has no server-side image / line items / splits yet.
        if (expenseId > 0) {
            loadThumbnail()
            loadExpenseItems()
            loadExpenseSplits()
        } else {
            markLocalOnlyDetailLoadsLoaded(expense)
        }
    }

    private fun markLocalOnlyDetailLoadsLoaded(expense: Expense?) {
        val localExpenseId = expense?.id ?: expenseId
        val parentAmountCents = expense?.amountCents
        val parentRowVersion = expense?.rowVersion ?: 0L
        _uiState.update {
            it.copy(
                expenseItems = ExpenseItems(
                    expenseId = localExpenseId,
                    parentAmountCents = parentAmountCents,
                    itemsTotalAmountCents = null,
                    mismatchCents = null,
                    items = emptyList(),
                    parentRowVersion = parentRowVersion,
                ),
                expenseSplits = ExpenseSplits(
                    expenseId = localExpenseId,
                    parentAmountCents = parentAmountCents,
                    splitsTotalAmountCents = null,
                    mismatchCents = null,
                    splits = emptyList(),
                    parentRowVersion = parentRowVersion,
                ),
                itemsLoading = false,
                splitsLoading = false,
                itemsLoadState = ExpenseDetailDataLoadState.Loaded,
                splitsLoadState = ExpenseDetailDataLoadState.Loaded,
                itemsMessage = null,
                splitsMessage = null,
                itemsMessageTone = MessageTone.Neutral,
                splitsMessageTone = MessageTone.Neutral,
            )
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
            _uiState.update {
                it.copy(
                    itemsLoading = true,
                    itemsLoadState = ExpenseDetailDataLoadState.Loading,
                    itemsMessage = null,
                    itemsMessageTone = MessageTone.Neutral,
                )
            }
            repository.fetchExpenseItems(expenseId)
                .onSuccess { items ->
                    _uiState.update {
                        it.copy(
                            expenseItems = items,
                            itemsLoading = false,
                            itemsLoadState = ExpenseDetailDataLoadState.Loaded,
                            itemsMessageTone = MessageTone.Neutral,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            itemsLoading = false,
                            itemsLoadState = ExpenseDetailDataLoadState.Failed,
                            itemsMessage = error.toUiText(R.string.expense_edit_items_load_failed),
                            itemsMessageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    private fun loadExpenseSplits() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    splitsLoading = true,
                    splitsLoadState = ExpenseDetailDataLoadState.Loading,
                    splitsMessage = null,
                    splitsMessageTone = MessageTone.Neutral,
                )
            }
            repository.fetchExpenseSplits(expenseId)
                .onSuccess { splits ->
                    _uiState.update {
                        it.copy(
                            expenseSplits = splits,
                            splitsLoading = false,
                            splitsLoadState = ExpenseDetailDataLoadState.Loaded,
                            splitsMessageTone = MessageTone.Neutral,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            splitsLoading = false,
                            splitsLoadState = ExpenseDetailDataLoadState.Failed,
                            splitsMessage = error.toUiText(R.string.expense_edit_splits_load_failed),
                            splitsMessageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun loadFullImage() {
        viewModelScope.launch {
            _uiState.update { it.copy(imageLoading = true, message = null, messageTone = MessageTone.Neutral) }
            repository.fetchImage(expenseId)
                .onSuccess { image -> _uiState.update { it.copy(fullImage = image, imageLoading = false) } }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            imageLoading = false,
                            message = error.toUiText(R.string.expense_edit_image_open_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun save(draft: ExpenseDraft) {
        if (blockReadOnlyWrite()) return
        viewModelScope.launch {
            val baseline = _uiState.value.expense
            val savesManualRate = draft.manualExchangeRate != null
            _uiState.update { it.copy(saving = true, message = null, messageTone = MessageTone.Neutral) }
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
                        _uiState.update {
                            it.copy(
                                expense = expense,
                                saving = false,
                                message = UiText.res(R.string.expense_edit_save_success),
                                messageTone = MessageTone.Success,
                                done = true,
                                // No baseline → full-field write → always
                                // payload-relevant.
                                doneAdviceInputsChanged = true,
                            )
                        }
                    }
                    .onFailure { error ->
                        _uiState.update {
                            it.copy(
                                saving = false,
                                message = error.toUiText(R.string.expense_edit_save_failed),
                                messageTone = MessageTone.Danger,
                            )
                        }
                    }
                return@launch
            }
            repository.saveExpenseAllowingOffline(expenseId, draft, baseline)
                .onSuccess { outcome ->
                    val feedback = expenseEditSaveFeedback(outcome, savesManualRate)
                    _uiState.update {
                        it.copy(
                            expense = outcome.expense,
                            saving = false,
                            message = feedback.message,
                            messageTone = feedback.tone,
                            done = feedback.done,
                            doneAdviceInputsChanged = draft.changesAdvisorPayloadAgainst(baseline),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            saving = false,
                            message = error.toUiText(R.string.expense_edit_save_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun confirm(draft: ExpenseDraft) {
        if (blockReadOnlyWrite()) return
        if (draft.amountCents == null && draft.originalAmountMinor == null) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.expense_edit_amount_required), messageTone = MessageTone.Danger)
            }
            return
        }
        val baseline = _uiState.value.expense
        if (baseline == null) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null, messageTone = MessageTone.Neutral) }
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
                            val (message, tone) = when (confirmOutcome) {
                                is ExpenseStateOutcome.Synced -> null to MessageTone.Neutral
                                is ExpenseStateOutcome.Queued ->
                                    UiText.res(R.string.expense_edit_confirm_offline_queued) to MessageTone.Info
                            }
                            _uiState.update { state ->
                                state.copy(
                                    expense = confirmOutcome.expense,
                                    saving = false,
                                    message = message,
                                    messageTone = tone,
                                    done = true,
                                    // Confirm adds the row to the confirmed set
                                    // the advisor aggregates — always relevant.
                                    doneAdviceInputsChanged = true,
                                )
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
                            _uiState.update { state ->
                                state.copy(
                                    expense = saveOutcome.expense,
                                    saving = false,
                                    message = error.toUiText(R.string.expense_edit_confirm_failed),
                                    messageTone = MessageTone.Danger,
                                )
                            }
                        }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            saving = false,
                            message = error.toUiText(R.string.expense_edit_save_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun reject() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null, messageTone = MessageTone.Neutral) }
            repository.rejectExpenseAllowingOffline(expense)
                .onSuccess { outcome ->
                    // Synced keeps the silent done→navigate-back behaviour;
                    // Queued surfaces the offline hint (mirrors save).
                    val (message, tone) = when (outcome) {
                        is ExpenseStateOutcome.Synced -> null to MessageTone.Neutral
                        is ExpenseStateOutcome.Queued ->
                            UiText.res(R.string.expense_edit_reject_offline_queued) to MessageTone.Info
                    }
                    _uiState.update {
                        it.copy(
                            saving = false,
                            message = message,
                            messageTone = tone,
                            done = true,
                            // Reject pulls a confirmed row OUT of the aggregated
                            // set — membership change is payload-relevant.
                            doneAdviceInputsChanged = true,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            saving = false,
                            message = error.toUiText(R.string.expense_edit_reject_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun retryOcr() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(ocrRunning = true, message = null, messageTone = MessageTone.Neutral) }
            repository.retryOcrAllowingOffline(expense)
                .onSuccess { outcome ->
                    val (message, tone) = when (outcome) {
                        is ExpenseStateOutcome.Synced ->
                            UiText.res(R.string.expense_edit_ocr_retried) to MessageTone.Success
                        is ExpenseStateOutcome.Queued ->
                            UiText.res(R.string.expense_edit_ocr_retry_offline_queued) to MessageTone.Info
                    }
                    _uiState.update {
                        it.copy(
                            expense = outcome.expense,
                            ocrRunning = false,
                            message = message,
                            messageTone = tone,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            ocrRunning = false,
                            message = error.toUiText(R.string.expense_edit_recognize_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    /** Open / close the "粘贴文字识别" input dialog. Gated on read-only at the
     *  UI layer (the affordance is hidden), but the open call also no-ops if the
     *  expense hasn't loaded so the dialog never opens on a half-loaded page. */
    fun openRecognizeTextDialog() {
        if (_uiState.value.expense == null) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded), messageTone = MessageTone.Danger)
            }
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
            _uiState.update {
                it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded), messageTone = MessageTone.Danger)
            }
            return
        }
        val text = rawText.trim()
        if (text.isBlank()) {
            _uiState.update {
                it.copy(
                    message = UiText.res(R.string.expense_edit_recognize_text_required),
                    messageTone = MessageTone.Danger,
                )
            }
            return
        }
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    ocrRunning = true,
                    recognizeTextDialogOpen = false,
                    message = null,
                    messageTone = MessageTone.Neutral,
                )
            }
            repository.recognizeTextAllowingOffline(expense, text)
                .onSuccess { outcome ->
                    val (message, tone) = when (outcome) {
                        // Server parsed the text and returned the refreshed expense;
                        // the Screen re-derives its field state from it (parsed
                        // result already filled the empty fields server-side).
                        is ExpenseStateOutcome.Synced ->
                            UiText.res(R.string.expense_edit_recognize_done) to MessageTone.Success
                        is ExpenseStateOutcome.Queued ->
                            UiText.res(R.string.expense_edit_recognize_offline_queued) to MessageTone.Info
                    }
                    _uiState.update {
                        it.copy(
                            expense = outcome.expense,
                            ocrRunning = false,
                            message = message,
                            messageTone = tone,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            ocrRunning = false,
                            message = error.toUiText(R.string.expense_edit_recognize_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun markNotDuplicate() {
        if (blockReadOnlyWrite()) return
        val expense = _uiState.value.expense
        if (expense == null) {
            _uiState.update {
                it.copy(message = UiText.res(R.string.expense_edit_page_not_loaded), messageTone = MessageTone.Danger)
            }
            return
        }
        viewModelScope.launch {
            repository.markNotDuplicateAllowingOffline(expense)
                .onSuccess { outcome ->
                    val (message, tone) = when (outcome) {
                        is ExpenseStateOutcome.Synced ->
                            UiText.res(R.string.expense_edit_keep_duplicate_success) to MessageTone.Success
                        is ExpenseStateOutcome.Queued ->
                            UiText.res(R.string.expense_edit_keep_duplicate_offline_queued) to MessageTone.Info
                    }
                    _uiState.update { it.copy(expense = outcome.expense, message = message, messageTone = tone) }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            message = error.toUiText(R.string.expense_edit_keep_duplicate_failed),
                            messageTone = MessageTone.Danger,
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

    fun consumeDoneAdviceInputsChanged(): Boolean {
        val changed = _uiState.value.doneAdviceInputsChanged
        if (changed) {
            _uiState.update { it.copy(doneAdviceInputsChanged = false) }
        }
        return changed
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
                message = UiText.res(R.string.common_readonly_ledger),
                messageTone = MessageTone.Danger,
            )
        }
        return true
    }
}

private data class ExpenseEditSaveFeedback(
    val message: UiText,
    val tone: MessageTone,
    val done: Boolean,
)

private fun expenseEditSaveFeedback(
    outcome: SaveOutcome,
    savesManualRate: Boolean,
): ExpenseEditSaveFeedback = when (outcome) {
    is SaveOutcome.Synced -> ExpenseEditSaveFeedback(
        message = UiText.res(
            if (savesManualRate) R.string.expense_edit_manual_rate_saved else R.string.expense_edit_save_success,
        ),
        tone = MessageTone.Success,
        done = !savesManualRate,
    )
    // Queued state is only a local intent. Manual FX stays open until the
    // canonical server projection arrives; ordinary edits keep prior behavior.
    is SaveOutcome.Queued -> ExpenseEditSaveFeedback(
        message = UiText.res(
            if (savesManualRate) {
                R.string.expense_edit_manual_rate_offline_queued
            } else {
                R.string.expense_edit_save_offline_queued
            },
        ),
        tone = MessageTone.Info,
        done = !savesManualRate,
    )
}

/**
 * Minor-unit → 输入框主单位文本，items / splits 编辑器扩展共用。按当前票据的服务端
 * `homeCurrency` 渲染（JPY 等零小数 home 不 ÷100），与保存侧的解析口径一致；
 * 票据未加载时落 [FxContract.HomeCurrency] 兜底（此时编辑器也未打开，不会触达）。
 * （文件级扩展：类体贴 detekt LargeClass 门，R14-1 起移出类。）
 */
internal fun ExpenseEditViewModel.centsToYuanText(cents: Long?): String {
    if (cents == null) return ""
    val expense = _uiState.value.expense
    // R14-1：原码严格解析 —— 未知码不缩放（原 minor 整数原样回填），不冒 CNY 两位
    // 口径把 1200 VND 写成 "12.00"；已知码维持 formatMinorAmountInput 同口径。
    val raw = expense?.homeCurrencyCode
    if (!raw.isNullOrBlank() && CurrencyCode.fromStorageKeyOrNull(raw) == null) {
        return abs(cents).toString()
    }
    val currency = expense?.homeCurrency ?: FxContract.HomeCurrency
    return formatMinorAmountInput(abs(cents), currency)
}

internal fun Expense.withParentRowVersion(parentRowVersion: Long): Expense =
    if (parentRowVersion > 0L && parentRowVersion != rowVersion) {
        copy(rowVersion = parentRowVersion)
    } else {
        this
    }

/**
 * 金额编辑（items/splits/bill-split）的解析币种（PR#255 R10④）：raw 码严格解析，未知码
 * （支持集外）→ null，调用方禁金额承载编辑；raw 缺失（旧 record / 手工构造的域对象）回落
 * 枚举口径（mapper 构造时已解析过该枚举，不再二次放宽）。
 */
internal fun Expense.editParseCurrency(): CurrencyCode? {
    val raw = homeCurrencyCode
    return if (raw.isNullOrBlank()) homeCurrency else CurrencyCode.fromStorageKeyOrNull(raw)
}

/**
 * 显示/均分侧的草稿解析币种（PR#255 R15b-2）：已知码同 [editParseCurrency]；未知码
 * 给 JPY 代理（原 minor 整数空间，与 footer 的 [parseAmountCentsForDisplay] 同口径，
 * 不按 FxContract 兜底放大 100×）；票据缺失回落 FxContract 兜底（防御，编辑器该态不开）。
 * 保存侧门禁仍看 [editParseCurrency] 的 null —— 本函数只决定显示/均分值。
 */
internal fun Expense?.editDisplayParseCurrency(): CurrencyCode {
    val expense = this ?: return FxContract.HomeCurrency
    return expense.editParseCurrency() ?: CurrencyCode.JPY
}
