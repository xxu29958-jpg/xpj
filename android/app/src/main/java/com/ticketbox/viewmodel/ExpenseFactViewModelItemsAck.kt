package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ItemsAckOutcome
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * A1 事实页「原小票如此」动作（明细差异的状态确认，非字段编辑）。
 *
 * 事实页不重建 pending 编辑器：本文件只持有这一条命令的 VM 接线，Owner 仍是
 * 既有 [com.ticketbox.data.repository.ExpenseFactActions.acknowledgeItemsMismatchAllowingOffline]
 * （OCC/幂等/Outbox 由 data 层既有实现承担）。结果诚实呈现：loading 禁用入口、
 * Synced 采用服务端快照、Queued 展示乐观 acknowledged 投影并说明联网后同步、
 * failure 走全局 banner 且差异保持可再试。
 */
fun ExpenseFactViewModel.acknowledgeItemsMismatch() {
    if (blockReadOnlyWrite()) return
    val expense = _uiState.value.expense
    val currentItems = _uiState.value.expenseItems
    if (expense == null || currentItems == null) {
        _uiState.update {
            it.copy(
                message = UiText.res(R.string.expense_edit_items_not_loaded_tap),
                messageTone = MessageTone.Danger,
            )
        }
        return
    }
    // 入口只在 mismatch_known 渲染；在途或已确认时静默忽略重复点击。
    if (_uiState.value.itemsLoading || !currentItems.mismatchKnown) return
    viewModelScope.launch {
        _uiState.update { it.copy(itemsLoading = true) }
        repository.acknowledgeItemsMismatchAllowingOffline(expense, currentItems)
            .onSuccess { outcome ->
                when (outcome) {
                    is ItemsAckOutcome.Synced -> _uiState.update {
                        it.copy(
                            expense = it.expense?.withParentRowVersion(outcome.items.parentRowVersion),
                            expenseItems = outcome.items,
                            itemsLoading = false,
                            itemsLoadState = ExpenseDetailDataLoadState.Loaded,
                            message = UiText.res(R.string.expense_edit_items_ack_synced),
                            messageTone = MessageTone.Success,
                        )
                    }
                    is ItemsAckOutcome.Queued -> _uiState.update {
                        // 离线：保留当前 token，展示乐观 acknowledged 投影；
                        // worker 联网后重放，revision 只认服务端。
                        it.copy(
                            expenseItems = outcome.items,
                            itemsLoading = false,
                            itemsLoadState = ExpenseDetailDataLoadState.Loaded,
                            message = UiText.res(R.string.expense_edit_items_ack_offline_queued),
                            messageTone = MessageTone.Info,
                        )
                    }
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        itemsLoading = false,
                        message = error.toUiText(R.string.expense_edit_items_ack_failed),
                        messageTone = MessageTone.Danger,
                    )
                }
            }
    }
}
