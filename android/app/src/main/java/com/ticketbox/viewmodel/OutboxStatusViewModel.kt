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
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxBinding
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.bindingOrNull
import com.ticketbox.data.repository.canonicalServerOriginOrNull
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
    private val _uiState = MutableStateFlow(OutboxStatusUiState(binding = expenseRepository.captureDeferredLedgerBinding()))
    val uiState: StateFlow<OutboxStatusUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            combine(outbox.observeStatus(), expenseRepository.observeCorrections(),
                debtAdjustments.observeAdjustments(), expenseRepository.observeLedgerAccess()) { status, corrections, adjustments, access ->
                Triple(status, corrections, adjustments) to access
            }.collect { (observations, access) ->
                val (observedStatus, corrections, adjustments) = observations
                val binding = access?.binding?.takeIf { it == expenseRepository.captureDeferredLedgerBinding() }
                val status = observedStatus.takeIf { it.binding.matches(binding) }
                    ?: OutboxStatus(0, emptyList(), emptyList())
                val currentCorrections = corrections.takeIf { it.access?.binding == binding }
                    ?: ExpenseCorrectionObservation(null, emptyList())
                val currentAdjustments = adjustments.adjustments.takeIf { adjustments.binding == binding }.orEmpty()
                val ready = binding != null && status.binding.matches(binding) &&
                    currentCorrections.access?.binding == binding && adjustments.binding == binding
                val descriptions = status.failed.mapNotNull { row ->
                    debtCreation.describePendingCreation(row)?.let { row.id to it }
                }.toMap()
                val occurrenceDescriptions = (status.failed + status.conflicts).mapNotNull { row ->
                    recurringOccurrences?.describe(row)?.let { row.id to it }
                }.toMap()
                val incomeDescriptions = (status.failed + status.conflicts).mapNotNull { row ->
                    incomePlans.describeEdit(row)?.let { row.id to it }
                }.toMap()
                val adjustmentDescriptions = currentAdjustments.filter {
                    it.row.status != com.ticketbox.data.local.PendingMutationStatus.Done
                }.associateBy { it.row.id }
                _uiState.update { previous ->
                    val state = previous.takeIf { it.binding == binding } ?: OutboxStatusUiState()
                    state.copy(binding = binding, bindingReady = ready,
                    correctionObservation = currentCorrections, status = status, failedDebtCreations = descriptions,
                    debtAdjustments = adjustmentDescriptions,
                    waitingDebtAdjustments = adjustmentDescriptions.values.filter {
                        it.row.status in setOf(com.ticketbox.data.local.PendingMutationStatus.Pending,
                            com.ticketbox.data.local.PendingMutationStatus.InFlight)
                    },
                    retryableOffsetIds = status.failed.filter { row ->
                        row.type == PendingMutationType.CreateExpenseOffset && expenseRepository.canReplayExpenseOffset(row)
                    }.map { it.id }.toSet(),
                    recurringOccurrences = occurrenceDescriptions, incomeEdits = incomeDescriptions) }
            }
        }
    }

    /** "用我的覆盖" — re-apply my change on top of the server's latest. */
    fun keepMine(row: OutboxRow) {
        val binding = expenseRepository.captureDeferredLedgerBinding()
        if (!_uiState.value.accepts(row, binding)) return
        if (row.type in setOf(PendingMutationType.CorrectExpense, PendingMutationType.UploadScreenshot)) return
        if (row.type == PendingMutationType.CreateExpenseOffset) {
            explainOffsetReview()
            return
        }
        if (_uiState.value.busyRowId != null) return
        viewModelScope.launch {
            if (!_uiState.value.accepts(row, expenseRepository.captureDeferredLedgerBinding())) return@launch
            _uiState.update { it.copy(busyRowId = row.id, message = null, messageTone = MessageTone.Neutral) }
            val token = freshExpenseToken(row)
            if (expenseRepository.captureDeferredLedgerBinding() != binding) return@launch
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
            if (expenseRepository.captureDeferredLedgerBinding() == binding) _uiState.update { it.copy(busyRowId = null) }
        }
    }

    /** "放弃我的改动" — discard the queued change; the server's version wins. */
    fun dropMine(row: OutboxRow) {
        if (!_uiState.value.accepts(row, expenseRepository.captureDeferredLedgerBinding())) return
        if (row.type == PendingMutationType.CorrectExpense) recoverCorrection(row, true)
        else if (row.type == PendingMutationType.RecordDebtAdjustment) recoverAdjustment(row, true)
        else resolve(row) { outbox.resolveConflict(row.id, ConflictResolution.DropMine) }
    }

    /** "重试" — flip a FAILED row back to PENDING for the next drain. */
    fun retry(row: OutboxRow) {
        if (!_uiState.value.accepts(row, expenseRepository.captureDeferredLedgerBinding())) return
        if (row.type == PendingMutationType.UploadScreenshot) {
            _uiState.update { it.copy(message = UiText.res(R.string.sync_status_upload_recovery_body), messageTone = MessageTone.Info) }
            return
        }
        if (row.type == PendingMutationType.CorrectExpense) {
            recoverCorrection(row, false)
            return
        }
        if (row.type == PendingMutationType.CreateExpenseOffset && !expenseRepository.canReplayExpenseOffset(row)) {
            explainOffsetReview()
            return
        }
        if (row.type == PendingMutationType.RecordDebtAdjustment) {
            recoverAdjustment(row, false)
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
        if (!_uiState.value.accepts(row, expenseRepository.captureDeferredLedgerBinding())) return
        if (row.type == PendingMutationType.CorrectExpense) recoverCorrection(row, true)
        else if (row.type == PendingMutationType.RecordDebtAdjustment) recoverAdjustment(row, true)
        else resolve(row) { outbox.resolveFailed(row.id, FailedResolution.Drop) }
    }

    private fun recoverAdjustment(row: OutboxRow, drop: Boolean) {
        val access = debtAdjustments.currentAccess()
        val pending = debtAdjustments.describeAdjustment(row)
        if (access == null || pending == null || !drop && !pending.hasSupportedIntent) {
            _uiState.update { it.copy(message = UiText.res(R.string.debt_adjustment_unsupported), messageTone = MessageTone.Danger) }
            return
        }
        if (!drop && !pending.canRetry) {
            val message = if (pending.reductionRejected) R.string.debt_adjustment_reduction_rejected else R.string.debt_adjustment_attention
            _uiState.update { it.copy(message = UiText.res(message), messageTone = MessageTone.Danger) }
            return
        }
        resolve(row) {
            debtAdjustments.recover(access.binding, pending, drop).onFailure { error ->
                if (expenseRepository.captureDeferredLedgerBinding() == access.binding) {
                    _uiState.update { it.copy(message = error.toUiText(R.string.debt_action_failed), messageTone = MessageTone.Danger) }
                }
            }
        }
    }

    private fun recoverCorrection(row: OutboxRow, drop: Boolean) {
        val binding = _uiState.value.correctionObservation.access?.binding ?: return
        resolve(row) {
            expenseRepository.recoverCorrection(binding, row.id, drop).onFailure { error ->
                if (expenseRepository.captureDeferredLedgerBinding() == binding) {
                    _uiState.update { it.copy(message = error.toUiText(R.string.expense_correction_failed), messageTone = MessageTone.Danger) }
                }
            }
        }
    }

    /** Remove only ownerless or foreign-owner rows after the screen confirms it. */
    fun clearQuarantined() {
        val binding = expenseRepository.captureDeferredLedgerBinding() ?: return
        if (!_uiState.value.bindingReady || _uiState.value.binding != binding) return
        if (_uiState.value.busyRowId != null || _uiState.value.isClearingQuarantine) return
        viewModelScope.launch {
            if (expenseRepository.captureDeferredLedgerBinding() != binding) return@launch
            _uiState.update {
                it.copy(isClearingQuarantine = true, message = null, messageTone = MessageTone.Neutral)
            }
            runCatching { outbox.clearQuarantined() }
                .onSuccess { removed ->
                    if (expenseRepository.captureDeferredLedgerBinding() != binding) return@onSuccess
                    _uiState.update {
                        it.copy(
                            isClearingQuarantine = false,
                            message = UiText.res(R.string.sync_status_quarantined_removed, removed),
                            messageTone = MessageTone.Success,
                        )
                    }
                }
                .onFailure {
                    if (expenseRepository.captureDeferredLedgerBinding() != binding) return@onFailure
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

    private fun explainOffsetReview() = _uiState.update {
        it.copy(message = UiText.res(R.string.expense_offset_original_requires_review), messageTone = MessageTone.Danger)
    }

    private fun resolve(row: OutboxRow, block: suspend () -> Unit) {
        val binding = expenseRepository.captureDeferredLedgerBinding()
        if (!_uiState.value.accepts(row, binding)) return
        if (_uiState.value.busyRowId != null) return
        viewModelScope.launch {
            if (expenseRepository.captureDeferredLedgerBinding() != binding) return@launch
            _uiState.update { it.copy(busyRowId = row.id, message = null, messageTone = MessageTone.Neutral) }
            try {
                block()
            } finally {
                if (expenseRepository.captureDeferredLedgerBinding() == binding) _uiState.update { it.copy(busyRowId = null) }
            }
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
    val binding: LogicalSessionBinding? = null,
    val bindingReady: Boolean = false,
    val correctionObservation: com.ticketbox.data.repository.ExpenseCorrectionObservation =
        com.ticketbox.data.repository.ExpenseCorrectionObservation(null, emptyList()),
    val status: OutboxStatus = OutboxStatus(queueDepth = 0, conflicts = emptyList(), failed = emptyList()),
    val failedDebtCreations: Map<Long, PendingDebtCreation> = emptyMap(),
    val recurringOccurrences: Map<Long, com.ticketbox.data.repository.PendingOccurrencePayment> = emptyMap(),
    val incomeEdits: Map<Long, com.ticketbox.data.repository.PendingIncomePlanEdit> = emptyMap(),
    val debtAdjustments: Map<Long, com.ticketbox.data.repository.PendingDebtAdjustment> = emptyMap(),
    val waitingDebtAdjustments: List<com.ticketbox.data.repository.PendingDebtAdjustment> = emptyList(),
    val retryableOffsetIds: Set<Long> = emptySet(),
    val busyRowId: Long? = null,
    val isClearingQuarantine: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
)

private fun OutboxBinding?.matches(binding: LogicalSessionBinding?): Boolean =
    this != null && binding != null && ownerStorageKey == binding.ownerKey && ledgerId == binding.ledgerId &&
        canonicalServerOriginOrNull(serverUrl)?.let { it == canonicalServerOriginOrNull(binding.serverUrl) } == true

private fun OutboxStatusUiState.accepts(row: OutboxRow, currentBinding: LogicalSessionBinding?): Boolean =
    bindingReady && binding == currentBinding && row.bindingOrNull().matches(currentBinding)

/** Required consumers for readable original-intent recovery at either navigation entrance. */
data class OutboxRecoveryRepositories(
    val debtCreation: DebtCreationActions,
    val recurringOccurrences: com.ticketbox.data.repository.RecurringOccurrenceActions?,
    val incomePlans: com.ticketbox.data.repository.IncomePlanActions,
    val debtAdjustments: com.ticketbox.data.repository.DebtAdjustmentActions,
)
