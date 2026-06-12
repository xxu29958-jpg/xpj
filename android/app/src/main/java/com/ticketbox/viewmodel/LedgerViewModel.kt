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
    val viewMode: LedgerViewMode = LedgerViewMode.Card,
    val lastSyncAt: String? = null,
    val syncing: Boolean = false,
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
                it.copy(readOnly = !repository.canModifyLedger(), syncing = true, message = null)
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
                            lastSyncAt = repository.lastConfirmedSyncAt(),
                            message = UiText.res(R.string.ledger_msg_sync_done),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(syncing = false, message = error.toUiText(R.string.ledger_msg_sync_failed))
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
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(readOnly = true, applyingBatch = false, message = readOnlyMessage()) }
            return
        }
        val selected = _uiState.value.selectedIds
        // Resolve to the full Expense objects (each carries its own rowVersion
        // token) from the synced confirmed cache, not the filtered view.
        val targets = allConfirmed.filter { it.id in selected }
        if (targets.isEmpty()) {
            _uiState.update { it.copy(message = UiText.res(R.string.ledger_msg_batch_no_selection)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(applyingBatch = true, message = null) }
            repository.applyConfirmedBatch(targets, category = category, tags = tags)
                .onSuccess { result ->
                    // A freshly-applied category / tag may be new — refresh the
                    // filter chips so it shows up immediately.
                    loadCategories()
                    loadTags()
                    _uiState.update {
                        it.copy(
                            applyingBatch = false,
                            selectionMode = false,
                            selectedIds = emptySet(),
                            selectedHaveTags = false,
                            message = batchResultMessage(result),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(applyingBatch = false, message = error.toUiText(R.string.ledger_msg_batch_failed))
                    }
                }
        }
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
