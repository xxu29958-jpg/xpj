package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.RecentMerchant
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.expenseLedgerMonth
import com.ticketbox.domain.model.filterConfirmedExpenses
import com.ticketbox.domain.model.recentLedgerMerchants
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

enum class LedgerViewMode {
    Card,
    List,
    Table,
}

data class LedgerSummaryUi(
    val totalAmountCents: Long = 0L,
    val itemCount: Int = 0,
    val monthFilter: String = "",
    val syncing: Boolean = false,
    val lastSyncAt: String? = null,
    val readOnly: Boolean = false,
)

data class LedgerFilterUi(
    val monthFilter: String = "",
    val categoryFilter: String = "",
    val tagFilter: String = "",
    val query: String = "",
    val hasFilters: Boolean = false,
)

data class LedgerUiState(
    val items: List<Expense> = emptyList(),
    val categories: List<String> = DEFAULT_EXPENSE_CATEGORIES,
    val tags: List<String> = emptyList(),
    val months: List<String> = emptyList(),
    val readOnly: Boolean = false,
    val exportFile: CsvExport? = null,
    val monthFilter: String = YearMonth.now().toString(),
    val categoryFilter: String = "",
    val tagFilter: String = "",
    val query: String = "",
    val viewMode: LedgerViewMode = LedgerViewMode.List,
    val lastSyncAt: String? = null,
    val syncing: Boolean = false,
    val syncedInCurrentSession: Boolean = false,
    val exporting: Boolean = false,
    val creatingManual: Boolean = false,
    // ADR-0042 Slice C: multi-select + batch-edit state. selectionMode toggles
    // the contextual action bar + per-row checkboxes; selectedIds is the set of
    // expense ids the bulk edit fans out over; applyingBatch gates the sheet
    // while the fan-out runs.
    val selectionMode: Boolean = false,
    val selectedIds: Set<Long> = emptySet(),
    // Whether ANY selected expense already has tags — drives the destructive
    // replace-tags confirm dialog. Computed in the VM from the full synced list
    // (the same source the fan-out resolves targets from), NOT the filtered view,
    // so a filter change can't slip a tagged row past the confirm gate.
    val selectedHaveTags: Boolean = false,
    val applyingBatch: Boolean = false,
    // Batch-edit sheet outcome channel: unlike manual-create (error shown INSIDE
    // the sheet), batch synced/queued/failed is reported PAGE-LEVEL via [message],
    // so the sheet must close on done EITHER WAY to reveal it. [batchDone] flips on
    // both success and failure; the screen acks via batchSettled() (mirrors the
    // manualCreateDone pattern, but closes on both arms because the result is
    // page-level — see applyBatch). Fixes the optimistic close: the sheet used to
    // dismiss in the onApply lambda BEFORE applyConfirmedBatch resolved, so the
    // `applyingBatch` disable flag was dead and a typed tag string was lost on close.
    val batchDone: Boolean = false,
    val message: UiText? = null,
    // Manual-create sheet outcome channel: the sheet stays open on failure
    // (so the typed form survives), shows [manualCreateError] inline, and only
    // closes once [manualCreateDone] flips — the screen acks both via
    // manualCreateSettled() (mirrors ExpenseEditUiState.done).
    val manualCreateDone: Boolean = false,
    val manualCreateError: UiText? = null,
    // Most-recently-used merchants (with their last category) derived from the
    // FULL confirmed cache (not the filtered view) — quick-fill chips on the
    // manual-entry sheet. A tap is a manual fill, so the "AI only fills blanks"
    // rule doesn't apply.
    val recentMerchants: List<RecentMerchant> = emptyList(),
) {
    val selectedCount: Int get() = selectedIds.size

    /**
     * 8.4: true only during the very first sync ever — no cached items, a sync
     * in flight, and no prior sync timestamp (fresh install). LedgerScreen shows
     * a skeleton list instead of the empty-state card in this window. A returning
     * user always has a non-null [lastSyncAt], so this never masks the genuine
     * "no expenses yet" empty state. Pure derivation, unit-testable.
     */
    val isFirstSync: Boolean
        get() = items.isEmpty() && syncing && lastSyncAt == null

    val showPageRefresh: Boolean
        get() = syncing && items.isEmpty()

    val summary: LedgerSummaryUi
        get() = LedgerSummaryUi(
            totalAmountCents = items.sumOf { it.amountCents ?: 0L },
            itemCount = items.size,
            monthFilter = monthFilter,
            syncing = syncing,
            lastSyncAt = lastSyncAt,
            readOnly = readOnly,
        )

    val filter: LedgerFilterUi
        get() = LedgerFilterUi(
            monthFilter = monthFilter,
            categoryFilter = categoryFilter,
            tagFilter = tagFilter,
            query = query,
            hasFilters = monthFilter.isNotBlank() ||
                categoryFilter.isNotBlank() ||
                tagFilter.isNotBlank() ||
                query.isNotBlank(),
        )
}

class LedgerViewModel(
    private val repository: LedgerActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        LedgerUiState(
            readOnly = !repository.canModifyLedger(),
            lastSyncAt = repository.lastConfirmedSyncAt(),
        ),
    )
    val uiState: StateFlow<LedgerUiState> = _uiState.asStateFlow()
    private var allConfirmed: List<Expense> = emptyList()

    init {
        loadCategories()
        loadTags()
        loadMonths()
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                allConfirmed = expenses
                _uiState.update { state ->
                    state.copy(
                        items = filterItems(expenses, state),
                        // Keep the replace-gate flag honest if the synced data
                        // changes while a selection is open.
                        selectedHaveTags = state.selectionMode &&
                            expenses.any { it.id in state.selectedIds && !it.tags.isNullOrBlank() },
                        recentMerchants = recentLedgerMerchants(expenses),
                    )
                }
            }
        }
        sync()
    }

    private fun loadCategories() {
        viewModelScope.launch {
            repository.categories()
                .onSuccess { categories -> _uiState.update { it.copy(categories = categories) } }
                .onFailure { _uiState.update { it.copy(categories = DEFAULT_EXPENSE_CATEGORIES) } }
        }
    }

    private fun loadMonths() {
        viewModelScope.launch {
            repository.months()
                .onSuccess { months -> _uiState.update { it.copy(months = months) } }
        }
    }

    private fun loadTags() {
        viewModelScope.launch {
            repository.tags()
                .onSuccess { tags -> _uiState.update { it.copy(tags = tags) } }
        }
    }

    private fun filterItems(expenses: List<Expense>, state: LedgerUiState): List<Expense> {
        return filterConfirmedExpenses(
            expenses = expenses,
            month = state.monthFilter,
            category = state.categoryFilter,
            tag = state.tagFilter,
            query = state.query,
        )
    }

    fun setMonthFilter(value: String) {
        _uiState.update { state ->
            state.copy(monthFilter = value, items = filterItems(allConfirmed, state.copy(monthFilter = value)))
        }
    }

    fun setCategoryFilter(value: String) {
        _uiState.update { state ->
            state.copy(categoryFilter = value, items = filterItems(allConfirmed, state.copy(categoryFilter = value)))
        }
    }

    /**
     * §三报表钻取:统计分类行点击带来的(月, 分类)一次性落位。原子置两个筛选并
     * 单次重过滤(连调 [setMonthFilter]+[setCategoryFilter] 会发两帧中间态);
     * 同时清掉 tag/query——钻取语义是「看这个月这个分类的全部明细」,残留的
     * 旧搜索词会让结果对不上统计数字。
     */
    fun applyDrillFilter(month: String, category: String) {
        _uiState.update { state ->
            val next = state.copy(
                monthFilter = month,
                categoryFilter = category,
                tagFilter = "",
                query = "",
            )
            next.copy(items = filterItems(allConfirmed, next))
        }
    }

    fun setTagFilter(value: String) {
        _uiState.update { state ->
            state.copy(tagFilter = value, items = filterItems(allConfirmed, state.copy(tagFilter = value)))
        }
    }

    fun setQuery(value: String) {
        _uiState.update { state ->
            state.copy(query = value, items = filterItems(allConfirmed, state.copy(query = value)))
        }
    }

    fun setViewMode(value: LedgerViewMode) {
        _uiState.update { state -> state.copy(viewMode = value) }
    }

    fun clearFilters() {
        _uiState.update { state ->
            val next = state.copy(monthFilter = "", categoryFilter = "", tagFilter = "", query = "")
            next.copy(items = filterItems(allConfirmed, next))
        }
    }

    fun sync() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    readOnly = !repository.canModifyLedger(),
                    syncing = true,
                    syncedInCurrentSession = false,
                    message = null,
                )
            }
            val filters = _uiState.value
            repository.syncConfirmed(
                month = filters.monthFilter.trim().ifBlank { null },
                category = filters.categoryFilter.trim().ifBlank { null },
                tag = filters.tagFilter.trim().ifBlank { null },
            )
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            syncing = false,
                            syncedInCurrentSession = true,
                            lastSyncAt = repository.lastConfirmedSyncAt(),
                            message = UiText.res(R.string.ledger_msg_sync_done),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            syncing = false,
                            syncedInCurrentSession = false,
                            message = error.toUiText(R.string.ledger_msg_sync_failed),
                        )
                    }
                }
        }
    }

    fun exportCsv() {
        viewModelScope.launch {
            val filters = _uiState.value
            if (filters.items.isEmpty()) {
                _uiState.update {
                    it.copy(message = UiText.res(R.string.ledger_msg_export_empty))
                }
                return@launch
            }
            _uiState.update { it.copy(exporting = true, message = null) }
            repository.exportConfirmedCsv(
                month = filters.monthFilter,
                category = filters.categoryFilter,
                tag = filters.tagFilter,
            )
                .onSuccess { exportFile ->
                    _uiState.update {
                        it.copy(exportFile = exportFile, exporting = false, message = UiText.res(R.string.ledger_msg_export_pick_location))
                    }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(exporting = false, message = error.toUiText(R.string.ledger_msg_export_failed)) }
                }
        }
    }

    fun createManualExpense(draft: ExpenseDraft) {
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(readOnly = true, creatingManual = false, message = readOnlyMessage()) }
            return
        }
        viewModelScope.launch {
            if (draft.amountCents == null && draft.originalAmountMinor == null) {
                _uiState.update { it.copy(message = UiText.res(R.string.error_amount_required)) }
                return@launch
            }
            _uiState.update { it.copy(creatingManual = true, message = null, manualCreateError = null) }
            repository.createManualExpense(draft)
                .onSuccess { expense ->
                    loadCategories()
                    loadTags()
                    loadMonths()
                    _uiState.update { state ->
                        val next = state.copy(
                            creatingManual = false,
                            manualCreateDone = true,
                            monthFilter = expenseLedgerMonth(expense) ?: state.monthFilter,
                            categoryFilter = "",
                            tagFilter = "",
                            message = UiText.res(R.string.ledger_msg_manual_saved),
                        )
                        next.copy(items = filterItems(allConfirmed, next))
                    }
                }
                .onFailure { error ->
                    // Surfaced INSIDE the still-open sheet (not page-level
                    // message): the sheet covers the page, and closing it on
                    // failure would destroy the typed form.
                    _uiState.update {
                        it.copy(creatingManual = false, manualCreateError = error.toUiText(R.string.ledger_msg_manual_save_failed))
                    }
                }
        }
    }

    /** Screen ack after the manual-create sheet closed (success) or was
     *  dismissed (gives up a failed attempt) — clears the outcome channel. */
    fun manualCreateSettled() {
        _uiState.update { it.copy(manualCreateDone = false, manualCreateError = null) }
    }

    // ADR-0042 Slice C — multi-select + batch edit -------------------------

    private fun withSelection(state: LedgerUiState, ids: Set<Long>): LedgerUiState =
        state.copy(
            selectionMode = true,
            selectedIds = ids,
            // From allConfirmed (the fan-out's target source), not the filtered view.
            selectedHaveTags = allConfirmed.any { it.id in ids && !it.tags.isNullOrBlank() },
        )

    fun enterSelection(initialId: Long? = null) {
        _uiState.update {
            withSelection(it, if (initialId != null) it.selectedIds + initialId else it.selectedIds)
        }
    }

    fun exitSelection() {
        _uiState.update { it.copy(selectionMode = false, selectedIds = emptySet(), selectedHaveTags = false) }
    }

    fun toggleSelected(id: Long) {
        _uiState.update { state ->
            val next = if (id in state.selectedIds) state.selectedIds - id else state.selectedIds + id
            // Leaving selection mode entirely is an explicit action (exitSelection);
            // unticking the last row keeps the bar open so the user can re-pick.
            withSelection(state, next)
        }
    }

    /** Select every expense currently visible under the active filters. */
    fun selectAllVisible() {
        _uiState.update { state -> withSelection(state, state.items.map { it.id }.toSet()) }
    }

    fun applyBatchCategory(category: String) = applyBatch(category = category, tags = null)

    fun applyBatchTags(tags: String) = applyBatch(category = null, tags = tags)

    private fun applyBatch(category: String?, tags: String?) {
        // Synchronous re-entry guard: applyingBatch is flipped synchronously below (BEFORE the
        // launch), so a double-tap during the dispatch+recomposition window can't fire a second
        // fan-out — the second would capture the same rowVersions, hit OCC conflicts on the
        // just-bumped rows, and report spurious failures. The `!applying` button disable lags
        // a frame; this guard closes the window deterministically.
        if (_uiState.value.applyingBatch) return
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(readOnly = true, applyingBatch = false, message = readOnlyMessage()) }
            return
        }
        val selected = _uiState.value.selectedIds
        // Resolve to the full Expense objects (each carries its own rowVersion
        // token) from the synced confirmed cache, not the filtered view.
        val targets = allConfirmed.filter { it.id in selected }
        if (targets.isEmpty()) {
            // Flip batchDone so the screen closes the sheet and the page-level no-selection
            // message becomes visible (the still-open sheet would otherwise cover it). Mirrors
            // the resolve arms — without this the close-on-batchDone migration would strand the
            // sheet here (regression vs the old eager close, which dismissed before applyBatch).
            _uiState.update { it.copy(batchDone = true, message = UiText.res(R.string.ledger_msg_batch_no_selection)) }
            return
        }
        _uiState.update { it.copy(applyingBatch = true, message = null) }
        viewModelScope.launch {
            repository.applyConfirmedBatch(targets, category = category, tags = tags)
                .onSuccess { result ->
                    // A freshly-applied category / tag may be new — refresh the
                    // filter chips so it shows up immediately.
                    loadCategories()
                    loadTags()
                    _uiState.update {
                        it.copy(
                            applyingBatch = false,
                            batchDone = true,
                            selectionMode = false,
                            selectedIds = emptySet(),
                            selectedHaveTags = false,
                            message = batchResultMessage(result),
                        )
                    }
                }
                .onFailure { error ->
                    // Close the sheet too (batchDone) so the page-level error is
                    // visible; selection is kept (not cleared) so the user can retry.
                    _uiState.update {
                        it.copy(applyingBatch = false, batchDone = true, message = error.toUiText(R.string.ledger_msg_batch_failed))
                    }
                }
        }
    }

    /** Screen ack after the batch-edit sheet closed (success or failure) —
     *  clears the one-shot outcome channel so it can't re-close the next sheet. */
    fun batchSettled() {
        _uiState.update { it.copy(batchDone = false) }
    }

    /**
     * Honest partial-success copy: the fan-out is non-atomic, so synced /
     * queued / failed are reported separately rather than a single "done".
     *
     * ADR-0044: a dynamic multi-segment sentence (0–3 count clauses, zero
     * clauses omitted) that a single format resource cannot express — each
     * clause is its own resourced [UiText.Res] and [UiText.Compound] joins
     * them at the presentation layer, where [LedgerScreen] now renders
     * `state.message`.
     */
    private fun batchResultMessage(result: BatchApplyResult): UiText {
        val parts = buildList {
            if (result.synced > 0) add(UiText.res(R.string.ledger_msg_batch_part_synced, result.synced))
            if (result.queued > 0) add(UiText.res(R.string.ledger_msg_batch_part_queued, result.queued))
            if (result.failed > 0) add(UiText.res(R.string.ledger_msg_batch_part_failed, result.failed))
        }
        if (parts.isEmpty()) return UiText.res(R.string.ledger_msg_batch_none)
        return UiText.compound(parts, "，")
    }

    fun exportLaunchHandled() {
        _uiState.update { it.copy(exportFile = null) }
    }

    fun exportFinished(message: String) {
        // The caller (LedgerRoute) resolves the post-save copy and passes the
        // already-resolved text here, so carry it through as a UiText.Raw
        // (byte-identical output). ADR-0044 wave 2.
        _uiState.update { it.copy(message = UiText.raw(message)) }
    }
}
