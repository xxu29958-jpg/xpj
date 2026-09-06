package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ConflictResolution
import com.ticketbox.data.repository.DebtCreationActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FailedResolution
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.data.repository.parseExpenseTargetRef
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
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
    private val debtCreation: DebtCreationActions,
    private val recurringOccurrences: com.ticketbox.data.repository.RecurringOccurrenceActions? = null,
    private val incomePlans: com.ticketbox.data.repository.IncomePlanActions,
    private val debtAdjustments: com.ticketbox.data.repository.DebtAdjustmentActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(OutboxStatusUiState())
    val uiState: StateFlow<OutboxStatusUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            expenseRepository.observeCorrections().collect { observation ->
                _uiState.update { it.copy(correctionObservation = observation) }
            }
        }
        viewModelScope.launch {
            outbox.observeStatus().combine(
                outbox.observeActiveByTypes(setOf(PendingMutationType.RecordDebtAdjustment)),
            ) { status, adjustments -> status to adjustments }.collect { (status, adjustments) ->
                val descriptions = status.failed.mapNotNull { row ->
                    debtCreation.describePendingCreation(row)?.let { row.id to it }
                }.toMap()
                val occurrenceDescriptions = (status.failed + status.conflicts).mapNotNull { row ->
                    recurringOccurrences?.describe(row)?.let { row.id to it }
                }.toMap()
                val incomeDescriptions = (status.failed + status.conflicts).mapNotNull { row ->
                    incomePlans.describeEdit(row)?.let { row.id to it }
                }.toMap()
                val adjustmentDescriptions = adjustments.mapNotNull { row ->
                    debtAdjustments.describeAdjustment(row)?.let { row.id to it }
                }.toMap()
                _uiState.update { it.copy(status = status, failedDebtCreations = descriptions,
                    debtAdjustments = adjustmentDescriptions,
                    waitingDebtAdjustments = adjustmentDescriptions.values.filter {
                        it.row.status in setOf(com.ticketbox.data.local.PendingMutationStatus.Pending,
                            com.ticketbox.data.local.PendingMutationStatus.InFlight)
                    },
                    recurringOccurrences = occurrenceDescriptions, incomeEdits = incomeDescriptions) }
            }
        }
    }

    /** "用我的覆盖" — re-apply my change on top of the server's latest. */
    fun keepMine(row: OutboxRow) {
        if (row.type == PendingMutationType.CorrectExpense) return
        if (_uiState.value.busyRowId != null) return
        viewModelScope.launch {
            _uiState.update { it.copy(busyRowId = row.id, message = null, messageTone = MessageTone.Neutral) }
            val token = freshExpenseToken(row)
            if (token == null) {
                _uiState.update {
                    it.copy(
                        busyRowId = null,
                        message = UiText.res(R.string.sync_status_vm_keep_mine_unavailable),
                        messageTone = MessageTone.Danger,
                    )
                }
                return@launch
            }
            outbox.resolveConflict(row.id, ConflictResolution.KeepMine(token))
            _uiState.update { it.copy(busyRowId = null) }
        }
    }

    /** "放弃我的改动" — discard the queued change; the server's version wins. */
    fun dropMine(row: OutboxRow) {
        if (row.type == PendingMutationType.CorrectExpense) recoverCorrection(row, true)
        else resolve(row) { outbox.resolveConflict(row.id, ConflictResolution.DropMine) }
    }

    /** "重试" — flip a FAILED row back to PENDING for the next drain. */
    fun retry(row: OutboxRow) {
        if (row.type == PendingMutationType.CorrectExpense) {
            recoverCorrection(row, false)
            return
        }
        if (row.type == PendingMutationType.RecordDebtAdjustment) {
            val access = debtAdjustments.currentAccess()
            val pending = debtAdjustments.describeAdjustment(row)
            if (access == null || pending?.hasSupportedIntent != true) {
                _uiState.update { it.copy(message = UiText.res(R.string.debt_adjustment_unsupported), messageTone = MessageTone.Danger) }
                return
            }
            if (!pending.canRetry) {
                _uiState.update { it.copy(message = UiText.res(if (pending.reductionRejected) {
                    R.string.debt_adjustment_reduction_rejected
                } else R.string.debt_adjustment_attention), messageTone = MessageTone.Danger) }
                return
            }
            resolve(row) {
                debtAdjustments.recover(access.binding, pending, false).onFailure { error ->
                    _uiState.update { it.copy(message = error.toUiText(R.string.debt_action_failed), messageTone = MessageTone.Danger) }
                }
            }
            return
        }
        if (row.type == PendingMutationType.UpdateIncomePlan && incomePlans.describeEdit(row)?.hasSupportedIntent != true) {
            _uiState.update { it.copy(message = UiText.res(R.string.income_plan_edit_unsupported), messageTone = MessageTone.Danger) }
            return
        }
        resolve(row) { outbox.resolveFailed(row.id, FailedResolution.Retry()) }
    }

    /** "放弃" — drop a FAILED row. */
    fun dropFailed(row: OutboxRow) {
        if (row.type == PendingMutationType.CorrectExpense) recoverCorrection(row, true)
        else resolve(row) { outbox.resolveFailed(row.id, FailedResolution.Drop) }
    }

    private fun recoverCorrection(row: OutboxRow, drop: Boolean) {
        val binding = _uiState.value.correctionObservation.access?.binding ?: return
        resolve(row) {
            expenseRepository.recoverCorrection(binding, row.id, drop).onFailure { error ->
                _uiState.update { it.copy(message = error.toUiText(R.string.expense_correction_failed), messageTone = MessageTone.Danger) }
            }
        }
    }

    /** Remove only ownerless or foreign-owner rows after the screen confirms it. */
    fun clearQuarantined() {
        if (_uiState.value.busyRowId != null || _uiState.value.isClearingQuarantine) return
        viewModelScope.launch {
            _uiState.update {
                it.copy(isClearingQuarantine = true, message = null, messageTone = MessageTone.Neutral)
            }
            runCatching { outbox.clearQuarantined() }
                .onSuccess { removed ->
                    _uiState.update {
                        it.copy(
                            isClearingQuarantine = false,
                            message = UiText.res(R.string.sync_status_quarantined_removed, removed),
                            messageTone = MessageTone.Success,
                        )
                    }
                }
                .onFailure {
                    _uiState.update {
                        it.copy(
                            isClearingQuarantine = false,
                            message = UiText.res(R.string.sync_status_quarantined_remove_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun consumeMessage() = _uiState.update { it.copy(message = null, messageTone = MessageTone.Neutral) }

    private fun resolve(row: OutboxRow, block: suspend () -> Unit) {
        if (_uiState.value.busyRowId != null) return
        viewModelScope.launch {
            _uiState.update { it.copy(busyRowId = row.id, message = null, messageTone = MessageTone.Neutral) }
            block()
            _uiState.update { it.copy(busyRowId = null) }
        }
    }

    private suspend fun freshExpenseToken(row: OutboxRow): Long? {
        // A device-local ``local:{client_ref}`` ref has no server row_version to
        // re-fetch yet (it gains a server id on sync, slice 4), so toLongOrNull()
        // yields null → keep-mine stays unavailable until the row is synced.
        val id = parseExpenseTargetRef(row.targetId)?.toLongOrNull() ?: return null
        return expenseRepository.fetchExpense(id).getOrNull()?.rowVersion
    }
}

data class OutboxStatusUiState(
    val correctionObservation: com.ticketbox.data.repository.ExpenseCorrectionObservation =
        com.ticketbox.data.repository.ExpenseCorrectionObservation(null, emptyList()),
    val status: OutboxStatus = OutboxStatus(queueDepth = 0, conflicts = emptyList(), failed = emptyList()),
    val failedDebtCreations: Map<Long, PendingDebtCreation> = emptyMap(),
    val recurringOccurrences: Map<Long, com.ticketbox.data.repository.PendingOccurrencePayment> = emptyMap(),
    val incomeEdits: Map<Long, com.ticketbox.data.repository.PendingIncomePlanEdit> = emptyMap(),
    val debtAdjustments: Map<Long, com.ticketbox.data.repository.PendingDebtAdjustment> = emptyMap(),
    val waitingDebtAdjustments: List<com.ticketbox.data.repository.PendingDebtAdjustment> = emptyList(),
    val busyRowId: Long? = null,
    val isClearingQuarantine: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
)

/** Required consumers for readable original-intent recovery at either navigation entrance. */
data class OutboxRecoveryRepositories(
    val debtCreation: DebtCreationActions,
    val recurringOccurrences: com.ticketbox.data.repository.RecurringOccurrenceActions?,
    val incomePlans: com.ticketbox.data.repository.IncomePlanActions,
    val debtAdjustments: com.ticketbox.data.repository.DebtAdjustmentActions,
)
