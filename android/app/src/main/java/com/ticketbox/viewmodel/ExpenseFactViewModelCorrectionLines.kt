package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * A1 更正流的明细/拆账子 surface（编辑器开关、draft 维护、采用/放弃、均分）。
 * 提交前的域 draft 构造与 baseline diff 在 [ExpenseFactViewModelCorrectionDrafts.kt]。
 */

fun ExpenseFactViewModel.openCorrectionItemsEditor() {
    val items = _uiState.value.expenseItems ?: return
    val expense = _uiState.value.expense ?: return
    val displayCurrency = expense.editDisplayParseCurrency()
    val drafts = items.items.map { item ->
        EditableItem(
            name = item.name,
            amountText = item.amountCents?.let { cents ->
                com.ticketbox.ui.components.formatMinorAmountInput(kotlin.math.abs(cents), displayCurrency)
            }.orEmpty(),
            kind = item.kind,
            quantityText = item.quantityText,
            unitPriceCents = item.unitPriceCents,
            category = item.category,
            rawText = item.rawText,
            confidence = item.confidence,
            baselineAmountCents = item.amountCents,
        )
    }
    updateCorrection { it.copy(itemsEditorOpen = true, itemDrafts = drafts) }
}

fun ExpenseFactViewModel.updateCorrectionItemDraft(
    index: Int,
    name: String?,
    amountText: String?,
    kind: String?,
) = updateCorrection { state ->
    val drafts = state.itemDrafts.toMutableList()
    val current = drafts.getOrNull(index) ?: return@updateCorrection state
    drafts[index] = current.copy(
        name = name ?: current.name,
        amountText = amountText ?: current.amountText,
        kind = kind ?: current.kind,
    )
    state.copy(itemDrafts = drafts)
}

fun ExpenseFactViewModel.addCorrectionItemRow() = updateCorrection {
    it.copy(itemDrafts = it.itemDrafts + EditableItem())
}

fun ExpenseFactViewModel.removeCorrectionItemRow(index: Int) = updateCorrection {
    it.copy(itemDrafts = it.itemDrafts.filterIndexed { i, _ -> i != index })
}

/** 明细编辑完成：draft 留在表单态里，打上「将随本次更正更新」标记。 */
fun ExpenseFactViewModel.adoptCorrectionItems() = updateCorrection {
    it.copy(itemsEditorOpen = false, itemsTouched = true)
}

fun ExpenseFactViewModel.dismissCorrectionItemsEditor() = updateCorrection {
    it.copy(itemsEditorOpen = false)
}

fun ExpenseFactViewModel.openCorrectionSplitsEditor() {
    val currentSplits = _uiState.value.expenseSplits ?: return
    val expense = _uiState.value.expense ?: return
    updateCorrection { it.copy(splitEditorOpen = true, splitMembersLoading = true) }
    viewModelScope.launch {
        repository.fetchSplitMembers()
            .onSuccess { members ->
                updateCorrection {
                    it.copy(
                        splitDrafts = buildCorrectionSplitDrafts(
                            expense = expense,
                            members = members,
                            currentSplits = currentSplits,
                        ),
                        splitMembersLoading = false,
                    )
                }
            }
            .onFailure { error ->
                updateCorrection { it.copy(splitMembersLoading = false) }
                _uiState.update {
                    it.copy(
                        message = error.toUiText(R.string.expense_edit_bill_split_members_load_failed),
                        messageTone = MessageTone.Danger,
                    )
                }
            }
    }
}

/** 勾选/金额共用一个更新入口（两个字段都是可选覆盖）。 */
fun ExpenseFactViewModel.updateCorrectionSplitDraft(
    memberId: Long,
    included: Boolean? = null,
    amountText: String? = null,
) = updateCorrection { state ->
    state.copy(
        splitDrafts = state.splitDrafts.map {
            if (it.memberId == memberId && !it.disabled) {
                it.copy(
                    included = included ?: it.included,
                    amountText = amountText ?: it.amountText,
                )
            } else {
                it
            }
        },
    )
}

fun ExpenseFactViewModel.adoptCorrectionSplits() = updateCorrection {
    it.copy(splitEditorOpen = false, splitsTouched = true)
}

/** 均分：把「父金额 − 停用成员固定额」按最大余数法摊到勾选的活跃成员，
 *  与编辑流同一算法（SplitsEditorSheet.evenSplitActiveCents）。 */
fun ExpenseFactViewModel.evenCorrectionSplitAmounts() = updateCorrection { state ->
    val parent = _uiState.value.expenseSplits?.parentAmountCents ?: return@updateCorrection state
    val checked = state.splitDrafts.filter { it.included && !it.disabled }
    if (checked.isEmpty()) return@updateCorrection state
    val currency = _uiState.value.expense.editDisplayParseCurrency()
    val fixedDisabledTotal = state.splitDrafts
        .filter { it.disabled }
        .sumOf { com.ticketbox.ui.components.parseAmountCents(it.amountText, currency) ?: 0L }
    val shares = com.ticketbox.ui.screens.expense.evenSplitActiveCents(parent, fixedDisabledTotal, checked.size)
    val shareByMember = checked.mapIndexed { index, draft -> draft.memberId to shares[index] }.toMap()
    state.copy(
        splitDrafts = state.splitDrafts.map { draft ->
            val share = shareByMember[draft.memberId]
            if (share == null) {
                draft
            } else {
                draft.copy(
                    amountText = com.ticketbox.ui.components.formatMinorAmountInput(share, currency),
                )
            }
        },
    )
}

fun ExpenseFactViewModel.dismissCorrectionSplitsEditor() = updateCorrection {
    it.copy(splitEditorOpen = false)
}
