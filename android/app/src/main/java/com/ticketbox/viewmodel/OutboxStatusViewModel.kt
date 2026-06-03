package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ConflictResolution
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FailedResolution
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0038 PR-2g.11: the user-facing half of the offline outbox.
 *
 * The dispatchers (PR-2g.3–.9) queue offline mutations and the drain
 * engine parks 409s as CONFLICT rows / dead rows as FAILED. Without a
 * surface to resolve those, the ADR invariant ("client never silently
 * overwrites; the user explicitly keeps or drops") is never delivered.
 * This VM observes [OutboxRepository.observeStatus] and exposes the
 * resolve branches.
 *
 * Token re-fetch for "keep mine": a 409 means the row's
 * ``expected_row_version`` is stale, and the 409 body intentionally
 * carries no fresh token (ADR §41), so we re-GET the resource. v1
 * supports the expense family (``expense:<id>`` — every dispatcher in
 * PR-2g.3–.9 targets it); other families (category_rule / merchant_alias)
 * are drop-only here and gain keep-mine in a follow-up.
 */
class OutboxStatusViewModel(
    private val outbox: OutboxRepository,
    private val expenseRepository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(OutboxStatusUiState())
    val uiState: StateFlow<OutboxStatusUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            outbox.observeStatus().collect { status ->
                _uiState.update { it.copy(status = status) }
            }
        }
    }

    /** "用我的覆盖" — re-apply my change on top of the server's latest. */
    fun keepMine(row: OutboxRow) {
        if (_uiState.value.busyRowId != null) return
        viewModelScope.launch {
            _uiState.update { it.copy(busyRowId = row.id, message = null) }
            val token = freshExpenseToken(row)
            if (token == null) {
                _uiState.update {
                    it.copy(
                        busyRowId = null,
                        message = "这条改动暂时只能放弃，或联网后在对应页面重做。",
                    )
                }
                return@launch
            }
            outbox.resolveConflict(row.id, ConflictResolution.KeepMine(token))
            _uiState.update { it.copy(busyRowId = null) }
        }
    }

    /** "放弃我的改动" — discard the queued change; the server's version wins. */
    fun dropMine(row: OutboxRow) = resolve(row) {
        outbox.resolveConflict(row.id, ConflictResolution.DropMine)
    }

    /** "重试" — flip a FAILED row back to PENDING for the next drain. */
    fun retry(row: OutboxRow) = resolve(row) {
        outbox.resolveFailed(row.id, FailedResolution.Retry())
    }

    /** "放弃" — drop a FAILED row. */
    fun dropFailed(row: OutboxRow) = resolve(row) {
        outbox.resolveFailed(row.id, FailedResolution.Drop)
    }

    fun consumeMessage() = _uiState.update { it.copy(message = null) }

    private fun resolve(row: OutboxRow, block: suspend () -> Unit) {
        if (_uiState.value.busyRowId != null) return
        viewModelScope.launch {
            _uiState.update { it.copy(busyRowId = row.id, message = null) }
            block()
            _uiState.update { it.copy(busyRowId = null) }
        }
    }

    private suspend fun freshExpenseToken(row: OutboxRow): Long? {
        val prefix = "expense:"
        if (!row.targetId.startsWith(prefix)) return null
        val id = row.targetId.removePrefix(prefix).toLongOrNull() ?: return null
        return expenseRepository.fetchExpense(id).getOrNull()?.rowVersion
    }
}

data class OutboxStatusUiState(
    val status: OutboxStatus = OutboxStatus(queueDepth = 0, conflicts = emptyList(), failed = emptyList()),
    val busyRowId: Long? = null,
    val message: String? = null,
)
