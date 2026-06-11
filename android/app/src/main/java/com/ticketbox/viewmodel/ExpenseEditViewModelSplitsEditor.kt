package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReplaceSplitsOutcome
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.screens.expense.evenSplitActiveCents
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 架构债 #5 — ExpenseEditViewModel 的拆账（splits）编辑器扩展。
 *
 * ADR-0042 Slice E-1 splits 编辑域，从 815 行的主 ViewModel 拆出。
 * 与主 ViewModel 同包，使用 `internal` 字段访问
 * （[PendingViewModelReviewActions 先例模式]）。纯物理移动：
 * 函数体与拆分前逐字节一致，行为零变化。
 */

/** Open the splits editor and load the ledger member roster. The drafts are
 *  built once members arrive (member checklist seeded from the current
 *  splits — see [loadSplitMembers]). No-op until splits have loaded. */
fun ExpenseEditViewModel.openSplitsEditor() {
    if (_uiState.value.expenseSplits == null) {
        _uiState.update { it.copy(splitsMessage = UiText.res(R.string.expense_edit_splits_not_loaded_tap)) }
        return
    }
    _uiState.update { it.copy(splitEditorOpen = true, splitsMessage = null) }
    loadSplitMembers()
}

/** Fetch the ledger member roster and merge it with the current splits into
 *  the editable checklist: members already on a split are pre-checked and
 *  carry their amount; disabled members already on a split stay visible
 *  read-only (historical attribution); other disabled members are dropped. */
fun ExpenseEditViewModel.loadSplitMembers() {
    val currentSplits = _uiState.value.expenseSplits ?: return
    viewModelScope.launch {
        _uiState.update { it.copy(splitMembersLoading = true, splitsMessage = null) }
        repository.fetchSplitMembers()
            .onSuccess { members ->
                _uiState.update {
                    it.copy(
                        splitDrafts = buildSplitDrafts(members, currentSplits),
                        splitMembersLoading = false,
                    )
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        splitMembersLoading = false,
                        splitsMessage = error.toUiText(R.string.expense_edit_splits_members_load_failed),
                    )
                }
            }
    }
}

fun ExpenseEditViewModel.updateSplitIncluded(memberId: Long, included: Boolean) {
    _uiState.update { state ->
        val drafts = state.splitDrafts.map { draft ->
            if (draft.memberId == memberId && !draft.disabled) {
                draft.copy(included = included)
            } else {
                draft
            }
        }
        state.copy(splitDrafts = drafts)
    }
}

fun ExpenseEditViewModel.updateSplitAmount(memberId: Long, amountText: String) {
    _uiState.update { state ->
        val drafts = state.splitDrafts.map { draft ->
            if (draft.memberId == memberId && !draft.disabled) {
                draft.copy(amountText = amountText)
            } else {
                draft
            }
        }
        state.copy(splitDrafts = drafts)
    }
}

/** Largest-remainder fill of the parent amount across the currently-checked
 *  members (by display order). One-shot — the user can still edit any amount
 *  afterwards. No-op if no editable members are checked. */
fun ExpenseEditViewModel.evenSplitAmounts() {
    _uiState.update { state ->
        val parent = state.expenseSplits?.parentAmountCents ?: return@update state
        val checked = state.splitDrafts.filter { it.included && !it.disabled }
        if (checked.isEmpty()) return@update state
        // Disabled members already on the split hold fixed amounts the user
        // can't edit — subtract them so 均分 distributes only the REMAINING
        // amount across the active members and 合计 actually reaches the parent
        // total (otherwise 差额 can never reach zero when a disabled share exists).
        val fixedDisabledTotal = state.splitDrafts
            .filter { it.disabled }
            .sumOf { parseAmountCents(it.amountText) ?: 0L }
        val shares = evenSplitActiveCents(parent, fixedDisabledTotal, checked.size)
        val shareByMember = checked.mapIndexed { index, draft -> draft.memberId to shares[index] }.toMap()
        val drafts = state.splitDrafts.map { draft ->
            val share = shareByMember[draft.memberId]
            if (share != null) draft.copy(amountText = centsToYuanText(share)) else draft
        }
        state.copy(splitDrafts = drafts)
    }
}

fun ExpenseEditViewModel.closeSplitsEditor() {
    _uiState.update { it.copy(splitEditorOpen = false, splitDrafts = emptyList()) }
}

/** Persist the edited splits. Mirrors [saveItems]: Synced refreshes the
 *  parent token + shows the saved splits; Queued keeps the optimistic
 *  projection and tells the user it'll sync. Disabled members already on a
 *  split are preserved (kept in the request with their existing amount). */
fun ExpenseEditViewModel.saveSplits() {
    val expense = _uiState.value.expense
    val currentSplits = _uiState.value.expenseSplits
    if (expense == null || currentSplits == null) {
        _uiState.update { it.copy(splitsMessage = UiText.res(R.string.expense_edit_items_not_loaded_retry)) }
        return
    }
    // ADR-0042 P1 data-loss guard: the sheet opens BEFORE the member roster
    // loads (loadSplitMembers is async), so splitDrafts can still be empty —
    // the load is in flight, or it failed. Saving then would send splits=[]
    // and the backend replace deletes every existing split first. Refuse to
    // save an editor that never finished loading (an empty splitDrafts means
    // not-loaded; an intentional "remove everyone" still has the unchecked
    // rows in splitDrafts, so this only blocks the never-loaded case).
    if (_uiState.value.splitMembersLoading || _uiState.value.splitDrafts.isEmpty()) {
        _uiState.update { it.copy(splitsMessage = UiText.res(R.string.expense_edit_splits_not_loaded_save)) }
        return
    }
    val draftRows = _uiState.value.splitDrafts
        .filter { (it.included || it.disabled) && it.amountText.isNotBlank() }
    // Audit P3 #11: same unparsable-amount guard as saveItems — "1.2.3" must
    // not silently land as a ¥0 split share.
    if (draftRows.any { parseAmountCents(it.amountText) == null }) {
        _uiState.update { it.copy(splitsMessage = UiText.res(R.string.expense_edit_splits_amount_unparsable)) }
        return
    }
    val drafts = draftRows.map { it.toDomainDraft() }
    viewModelScope.launch {
        _uiState.update { it.copy(splitsSaving = true, splitsMessage = null) }
        repository.replaceExpenseSplitsAllowingOffline(expense, drafts, currentSplits)
            .onSuccess { outcome ->
                when (outcome) {
                    is ReplaceSplitsOutcome.Synced -> {
                        // Replace bumps the parent's row_version server-side;
                        // refresh the token so later same-page mutations don't
                        // race a stale one. Inline refresh (not loadExpense)
                        // keeps the success banner visible.
                        val refreshed = repository.fetchExpense(expense.id).getOrNull()
                        _uiState.update {
                            it.copy(
                                expense = refreshed ?: it.expense,
                                expenseSplits = outcome.splits,
                                splitEditorOpen = false,
                                splitDrafts = emptyList(),
                                splitsSaving = false,
                                message = UiText.res(R.string.expense_edit_splits_saved),
                            )
                        }
                    }
                    is ReplaceSplitsOutcome.Queued -> {
                        _uiState.update {
                            it.copy(
                                expenseSplits = outcome.splits,
                                splitEditorOpen = false,
                                splitDrafts = emptyList(),
                                splitsSaving = false,
                                message = UiText.res(R.string.expense_edit_splits_saved_offline_queued),
                            )
                        }
                    }
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        splitsSaving = false,
                        splitsMessage = error.toUiText(R.string.expense_edit_splits_save_failed),
                    )
                }
            }
    }
}

private fun ExpenseEditViewModel.buildSplitDrafts(
    members: List<FamilyMember>,
    currentSplits: ExpenseSplits,
): List<EditableSplit> {
    val splitByMember = currentSplits.splits.associateBy { it.memberId }
    // Members on a split that the roster no longer lists (disabled + dropped
    // from /members) still need a read-only row so we don't silently lose
    // their historical attribution on save.
    val rosterMemberIds = members.map { it.memberId }.toSet()
    val orphanedSplits = currentSplits.splits.filter { it.memberId !in rosterMemberIds }

    val rosterDrafts = members.mapNotNull { member ->
        val existing = splitByMember[member.memberId]
        when {
            // Active member: a row regardless of whether they're on a split.
            !member.isDisabled -> EditableSplit(
                memberId = member.memberId,
                displayName = member.displayName,
                included = existing != null,
                amountText = existing?.let { centsToYuanText(it.amountCents) }.orEmpty(),
                disabled = false,
            )
            // Disabled member already on a split: keep, read-only.
            existing != null -> EditableSplit(
                memberId = member.memberId,
                displayName = member.displayName,
                included = true,
                amountText = centsToYuanText(existing.amountCents),
                disabled = true,
            )
            // Disabled member NOT on a split: drop (can't add a disabled member).
            else -> null
        }
    }
    val orphanDrafts = orphanedSplits.map { split ->
        EditableSplit(
            memberId = split.memberId,
            displayName = split.accountName.ifBlank { "未命名成员" },
            included = true,
            amountText = centsToYuanText(split.amountCents),
            disabled = true,
        )
    }
    return rosterDrafts + orphanDrafts
}

private fun EditableSplit.toDomainDraft(): ExpenseSplitDraft = ExpenseSplitDraft(
    memberId = memberId,
    amountCents = parseAmountCents(amountText) ?: 0L,
    note = null,
)
