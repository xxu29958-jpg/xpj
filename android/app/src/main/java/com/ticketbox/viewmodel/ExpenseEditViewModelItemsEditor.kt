package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ItemsAckOutcome
import com.ticketbox.data.repository.ReplaceItemsOutcome
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import kotlin.math.abs
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 架构债 #5 — ExpenseEditViewModel 的小票明细（items）编辑器扩展。
 *
 * PR-D items 编辑器 + PR-2g.9 acknowledge-mismatch 同属一个编辑域，
 * 从 815 行的主 ViewModel 拆出。与主 ViewModel 同包，使用 `internal`
 * 字段访问（[PendingViewModelReviewActions 先例模式]）。纯物理移动：
 * 函数体与拆分前逐字节一致，行为零变化。
 */

fun ExpenseEditViewModel.acknowledgeItemsMismatch() {
    // ADR-0038 PR-2e/2g.9: pass the whole expense (token) + current
    // items so the offline path can build the optimistic projection.
    // Bail with the same items-message UX if either hasn't loaded.
    val expense = _uiState.value.expense
    val currentItems = _uiState.value.expenseItems
    if (expense == null || currentItems == null) {
        _uiState.update {
            it.copy(itemsMessage = UiText.res(R.string.expense_edit_items_not_loaded_tap))
        }
        return
    }
    viewModelScope.launch {
        _uiState.update { it.copy(itemsLoading = true, itemsMessage = null) }
        repository.acknowledgeItemsMismatchAllowingOffline(expense, currentItems)
            .onSuccess { outcome ->
                when (outcome) {
                    is ItemsAckOutcome.Synced -> {
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
                        val refreshedExpense = repository.fetchExpense(expense.id).getOrNull()
                        _uiState.update {
                            it.copy(
                                expense = refreshedExpense ?: it.expense,
                                expenseItems = outcome.items,
                                itemsLoading = false,
                                message = UiText.res(R.string.expense_edit_items_ack_synced),
                            )
                        }
                    }
                    is ItemsAckOutcome.Queued -> {
                        // Offline: no fetchExpense (network down) — keep the
                        // current token and show the optimistic acknowledged
                        // items. The worker replays the ack on reconnect.
                        _uiState.update {
                            it.copy(
                                expenseItems = outcome.items,
                                itemsLoading = false,
                                message = UiText.res(R.string.expense_edit_items_ack_offline_queued),
                            )
                        }
                    }
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        itemsLoading = false,
                        itemsMessage = error.toUiText(R.string.expense_edit_items_ack_failed),
                    )
                }
            }
    }
}

/** Open the editor seeded from the currently-loaded items (amount magnitude
 *  as text; the kind chip carries the sign). No-op until items have loaded. */
fun ExpenseEditViewModel.openItemsEditor() {
    val items = _uiState.value.expenseItems ?: return
    val drafts = items.items.map { item ->
        EditableItem(
            name = item.name,
            amountText = centsToYuanText(item.amountCents),
            kind = item.kind,
        )
    }
    _uiState.update { it.copy(itemEditorOpen = true, itemDrafts = drafts, itemsMessage = null) }
}

fun ExpenseEditViewModel.updateItemDraft(index: Int, name: String? = null, amountText: String? = null, kind: String? = null) {
    _uiState.update { state ->
        val drafts = state.itemDrafts.toMutableList()
        val current = drafts.getOrNull(index) ?: return@update state
        drafts[index] = current.copy(
            name = name ?: current.name,
            amountText = amountText ?: current.amountText,
            kind = kind ?: current.kind,
        )
        state.copy(itemDrafts = drafts)
    }
}

fun ExpenseEditViewModel.addItemRow() {
    _uiState.update { it.copy(itemDrafts = it.itemDrafts + EditableItem()) }
}

fun ExpenseEditViewModel.removeItemRow(index: Int) {
    _uiState.update { state ->
        val drafts = state.itemDrafts.toMutableList()
        if (index in drafts.indices) drafts.removeAt(index)
        state.copy(itemDrafts = drafts)
    }
}

fun ExpenseEditViewModel.closeItemsEditor() {
    _uiState.update { it.copy(itemEditorOpen = false, itemDrafts = emptyList()) }
}

/** Persist the edited items. Mirrors [acknowledgeItemsMismatch]'s outcome
 *  handling: Synced refreshes the parent token + shows the saved items;
 *  Queued keeps the optimistic projection and tells the user it'll sync. */
fun ExpenseEditViewModel.saveItems() {
    val expense = _uiState.value.expense
    val currentItems = _uiState.value.expenseItems
    if (expense == null || currentItems == null) {
        _uiState.update { it.copy(itemsMessage = UiText.res(R.string.expense_edit_items_not_loaded_retry)) }
        return
    }
    val drafts = _uiState.value.itemDrafts
        .filter { it.name.isNotBlank() || it.amountText.isNotBlank() }
        .map { it.toDomainDraft() }
    viewModelScope.launch {
        _uiState.update { it.copy(itemsSaving = true, itemsMessage = null) }
        repository.replaceExpenseItemsAllowingOffline(expense, drafts, currentItems)
            .onSuccess { outcome ->
                when (outcome) {
                    is ReplaceItemsOutcome.Synced -> {
                        // Replace bumps the parent's updated_at server-side;
                        // refresh the token so later same-page mutations don't
                        // race a stale one. Inline refresh (not loadExpense)
                        // keeps the success banner visible.
                        val refreshed = repository.fetchExpense(expense.id).getOrNull()
                        _uiState.update {
                            it.copy(
                                expense = refreshed ?: it.expense,
                                expenseItems = outcome.items,
                                itemEditorOpen = false,
                                itemDrafts = emptyList(),
                                itemsSaving = false,
                                message = UiText.res(R.string.expense_edit_items_saved),
                            )
                        }
                    }
                    is ReplaceItemsOutcome.Queued -> {
                        _uiState.update {
                            it.copy(
                                expenseItems = outcome.items,
                                itemEditorOpen = false,
                                itemDrafts = emptyList(),
                                itemsSaving = false,
                                message = UiText.res(R.string.expense_edit_items_saved_offline_queued),
                            )
                        }
                    }
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        itemsSaving = false,
                        itemsMessage = error.toUiText(R.string.expense_edit_items_save_failed),
                    )
                }
            }
    }
}

private fun EditableItem.toDomainDraft(): ExpenseItemDraft {
    val magnitude = parseAmountCents(amountText) ?: 0L
    // ADR-0035: discount lines carry negative amount_cents; the editor takes
    // the magnitude and the kind chip decides the sign.
    val signed = if (kind == ExpenseItemKind.DISCOUNT) -abs(magnitude) else magnitude
    return ExpenseItemDraft(
        name = name.trim().ifBlank { "未命名" },
        quantityText = null,
        unitPriceCents = null,
        amountCents = signed,
        category = null,
        rawText = null,
        confidence = null,
        kind = kind,
    )
}
