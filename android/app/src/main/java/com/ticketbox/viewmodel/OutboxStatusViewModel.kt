package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.DEBT_WRITE_TYPES
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
import com.ticketbox.data.repository.requiresManualCreateReview
import com.ticketbox.data.repository.MANUAL_CREATE_RECEIPT_REVIEW
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private val recurringSubmissionTypes = setOf(
    PendingMutationType.CreateRecurringItem, PendingMutationType.UpdateRecurringItem, PendingMutationType.SetRecurringOccurrencePayment,
)
internal val categoryRuleSubmissionTypes = setOf(
    PendingMutationType.CreateCategoryRule, PendingMutationType.UpdateCategoryRule, PendingMutationType.DeleteCategoryRule,
)
internal val incomePlanSubmissionTypes = setOf(PendingMutationType.CreateIncomePlan, PendingMutationType.UpdateIncomePlan)
private val writerSubmissionTypes = setOf(
    PendingMutationType.UpdateGoal, PendingMutationType.CreateGoal, PendingMutationType.SaveMonthlyBudget,
    PendingMutationType.SaveManualExchangeRate,
) + recurringSubmissionTypes + categoryRuleSubmissionTypes + incomePlanSubmissionTypes
private val originalSubmissionTypes = writerSubmissionTypes + PendingMutationType.CorrectExpense

private val submissionFailureResources = mapOf(
    PendingMutationType.CreateIncomePlan to R.string.income_plan_submission_unavailable,
    PendingMutationType.UpdateIncomePlan to R.string.income_plan_submission_unavailable,
    PendingMutationType.UpdateGoal to R.string.spending_goal_recovery_unavailable,
    PendingMutationType.CreateGoal to R.string.spending_goal_recovery_unavailable,
    PendingMutationType.SaveMonthlyBudget to R.string.budget_save_attention,
    PendingMutationType.SaveManualExchangeRate to R.string.advice_rate_submission_review,
    PendingMutationType.CreateRecurringItem to R.string.recurring_original_attention,
    PendingMutationType.UpdateRecurringItem to R.string.recurring_original_attention,
    PendingMutationType.SetRecurringOccurrencePayment to R.string.occurrence_attention,
    PendingMutationType.CreateCategoryRule to R.string.category_rule_submission_unavailable,
    PendingMutationType.UpdateCategoryRule to R.string.category_rule_submission_unavailable,
    PendingMutationType.DeleteCategoryRule to R.string.category_rule_submission_unavailable,
)

/**
 * Both Sync entrances observe the active binding's outbox and reuse each command owner's recovery.
 * Original planning submissions retain their captured request and key; only legacy expense edits
 * may explicitly request a fresh expense version for Keep Mine.
 */
class OutboxStatusViewModel(
    private val outbox: OutboxRepository,
    private val expenseRepository: ExpenseRepository,
    private val recoveries: OutboxRecoveryRepositories,
) : ViewModel() {
    private val _uiState = MutableStateFlow(OutboxStatusUiState(binding = expenseRepository.captureDeferredLedgerBinding()))
    val uiState: StateFlow<OutboxStatusUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            combine(outbox.observeStatus(), expenseRepository.observeCorrections(),
                recoveries.debtWrites.observeWrites(), expenseRepository.observeLedgerAccess(),
                outbox.observeActiveByTypes(incomePlanSubmissionTypes + setOf(PendingMutationType.SaveManualExchangeRate,
                    PendingMutationType.CreateExpense), includeCompleted = true)) { status, corrections, writes, access, incomeRows ->
                Triple(Triple(status, corrections, writes), access, incomeRows)
            }.collect { (observations, access, incomeRows) ->
                val (observedStatus, corrections, writes) = observations
                val binding = access?.binding?.takeIf { it == expenseRepository.captureDeferredLedgerBinding() }
                val status = observedStatus.takeIf { it.binding.matches(binding) }
                    ?: OutboxStatus(0, emptyList(), emptyList())
                val currentCorrections = corrections.takeIf { it.access?.binding == binding }
                    ?: ExpenseCorrectionObservation(null, emptyList())
                val currentWrites = writes.writes.takeIf { writes.binding == binding }.orEmpty()
                val ready = binding != null && status.binding.matches(binding) &&
                    currentCorrections.access?.binding == binding && writes.binding == binding
                val descriptions = status.failed.mapNotNull { row ->
                    recoveries.debtCreation.describePendingCreation(row)?.let { row.id to it }
                }.toMap()
                val occurrenceDescriptions = (status.failed + status.conflicts).mapNotNull { row ->
                    recoveries.recurringOccurrences?.describe(row)?.let { row.id to it }
                }.toMap()
                val incomeDescriptions = incomeRows.mapNotNull { row ->
                    recoveries.incomePlans.describeSubmission(row)?.let { row.id to it }
                }.toMap()
                val manualCreations = incomeRows.filter { it.bindingOrNull().matches(binding) }.mapNotNull { row ->
                    expenseRepository.describeManualCreation(row)?.let { row.id to it }
                }.toMap()
                if (binding != expenseRepository.captureDeferredLedgerBinding()) return@collect
                val writeDescriptions = currentWrites.filter {
                    it.row.status != com.ticketbox.data.local.PendingMutationStatus.Done
                }.associateBy { it.row.id }
                _uiState.update { previous ->
                    val state = previous.takeIf { it.binding == binding } ?: OutboxStatusUiState()
                    state.copy(binding = binding, bindingReady = ready,
                    correctionObservation = currentCorrections, status = status, failedDebtCreations = descriptions,
                    billSplitCreations = status.failed.mapNotNull { row -> expenseRepository.describeBillSplitCreation(row)?.let { row.id to it } }.toMap(),
                    debtWrites = writeDescriptions,
                    waitingDebtWrites = writeDescriptions.values.filter {
                        it.row.status in setOf(com.ticketbox.data.local.PendingMutationStatus.Pending,
                            com.ticketbox.data.local.PendingMutationStatus.InFlight)
                    },
                    retryableOffsetIds = status.failed.filter { row ->
                        row.type == PendingMutationType.CreateExpenseOffset && expenseRepository.canReplayExpenseOffset(row)
                    }.map { it.id }.toSet(),
                    recurringOccurrences = occurrenceDescriptions, incomeSubmissions = incomeDescriptions,
                    manualCreations = manualCreations,
                    manualRates = incomeRows.mapNotNull { row -> recoveries.budgetSaves.describeRate(row)?.let { row.id to it } }.toMap(),
                    goalEdits = (status.failed + status.conflicts).mapNotNull { row -> recoveries.goalEdits.describeEdit(row)?.let { row.id to it } }.toMap(),
                    goalCreations = (status.failed + status.conflicts).mapNotNull { row ->
                        recoveries.goalEdits.describeCreation(row)?.let { row.id to it }
                    }.toMap(),
                    recurringItems = (status.failed + status.conflicts).mapNotNull { row ->
                        recoveries.recurringItems.describeManualIntent(row)?.let { row.id to it }
                    }.toMap(),
                    categoryRules = (status.failed + status.conflicts).mapNotNull { row ->
                        recoveries.rules.describeSubmission(row)?.let { row.id to it }
                    }.toMap(),
                    budgetSaves = (status.failed + status.conflicts).mapNotNull { row -> recoveries.budgetSaves.describeSave(row)?.let { row.id to it } }.toMap()) }
            }
        }
    }

    /** "用我的覆盖" — re-apply my change on top of the server's latest. */
    fun keepMine(row: OutboxRow) {
        if (row.type == PendingMutationType.CreateExpense) return
        if (row.type in originalSubmissionTypes || row.type in DEBT_WRITE_TYPES ||
            row.type == PendingMutationType.CreateBillSplitInvitation) return
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

    /** Stop this local submission; the command owner does not undo a possible server acceptance. */
    fun dropMine(row: OutboxRow) {
        if (!_uiState.value.accepts(row, expenseRepository.captureDeferredLedgerBinding())) return
        if (row.type == PendingMutationType.CreateExpense) { recoverSubmission(row, true); return }
        if (row.type == PendingMutationType.UploadScreenshot) return
        if (row.type in originalSubmissionTypes) recoverSubmission(row, true)
        else if (row.type in DEBT_WRITE_TYPES) recoverDebtWrite(row, true)
        else resolve(row) { outbox.resolveConflict(row.id, ConflictResolution.DropMine) }
    }

    /** "重试" — flip a FAILED row back to PENDING for the next drain. */
    fun retry(row: OutboxRow) {
        if (row.type == PendingMutationType.CreateBillSplitInvitation) { recoverSubmission(row, false); return }
        if (!_uiState.value.accepts(row, expenseRepository.captureDeferredLedgerBinding())) return
        if (row.type == PendingMutationType.UploadScreenshot) {
            _uiState.update { it.copy(message = UiText.res(R.string.sync_status_upload_recovery_body), messageTone = MessageTone.Info) }
            return
        }
        if (row.type in originalSubmissionTypes) {
            recoverSubmission(row, false)
            return
        }
        if (row.type == PendingMutationType.CreateExpenseOffset && !expenseRepository.canReplayExpenseOffset(row)) {
            explainOffsetReview()
            return
        }
        if (row.type in DEBT_WRITE_TYPES) {
            recoverDebtWrite(row, false)
            return
        }
        resolve(row) {
            // A rendered button may carry an earlier failure; Room owns the current refusal.
            val current = outbox.observeStatus().first().failed.singleOrNull { it.id == row.id } ?: return@resolve
            if (!_uiState.value.accepts(current, expenseRepository.captureDeferredLedgerBinding())) return@resolve
            if (_uiState.value.offersRetry(current)) {
                outbox.resolveFailed(current.id, FailedResolution.Retry())
            } else {
                val message = if (current.lastError?.startsWith(MANUAL_CREATE_RECEIPT_REVIEW) == true)
                    R.string.error_manual_create_original_requires_review else R.string.ledger_manual_original_unverified
                _uiState.update { it.copy(message = UiText.res(message),
                    messageTone = MessageTone.Danger) }
            }
        }
    }

    /** "放弃" — drop a FAILED row. */
    fun dropFailed(row: OutboxRow) {
        if (row.type == PendingMutationType.CreateBillSplitInvitation) { recoverSubmission(row, true); return }
        if (!_uiState.value.accepts(row, expenseRepository.captureDeferredLedgerBinding())) return
        if (row.type == PendingMutationType.CreateExpense) { recoverSubmission(row, true); return }
        if (row.type == PendingMutationType.UploadScreenshot) return
        if (row.type in originalSubmissionTypes) recoverSubmission(row, true)
        else if (row.type in DEBT_WRITE_TYPES) recoverDebtWrite(row, true)
        else resolve(row) { outbox.resolveFailed(row.id, FailedResolution.Drop) }
    }

    private fun recoverDebtWrite(row: OutboxRow, drop: Boolean) {
        val access = recoveries.debtWrites.currentAccess()
        val pending = recoveries.debtWrites.describeWrite(row)
        if (access == null || pending == null || !drop && !pending.hasSupportedIntent) {
            _uiState.update { it.copy(message = UiText.res(R.string.debt_write_unsupported), messageTone = MessageTone.Danger) }
            return
        }
        if (!drop && !pending.canRetry) {
            val message = if (pending.reductionRejected) R.string.debt_adjustment_reduction_rejected else R.string.debt_write_attention
            _uiState.update { it.copy(message = UiText.res(message), messageTone = MessageTone.Danger) }
            return
        }
        resolve(row) {
            recoveries.debtWrites.recover(access.binding, pending, drop).onFailure { error ->
                if (expenseRepository.captureDeferredLedgerBinding() == access.binding) {
                    _uiState.update { it.copy(message = error.toUiText(R.string.debt_action_failed), messageTone = MessageTone.Danger) }
                }
            }
        }
    }

    private fun recoverSubmission(row: OutboxRow, drop: Boolean) {
        if (!_uiState.value.accepts(row, expenseRepository.captureDeferredLedgerBinding())) return
        val binding = _uiState.value.binding ?: return
        resolve(row) {
            val result = when (row.type) {
                PendingMutationType.CreateExpense -> expenseRepository.stopManualCreation(row)
                PendingMutationType.CreateBillSplitInvitation -> expenseRepository.recoverBillSplitCreation(binding, row.id, drop)
                else -> recoveries.recoverPlanningSubmission(binding, row, drop)
                    ?: expenseRepository.recoverCorrection(binding, row.id, drop)
            }
            result.onFailure { error ->
                if (expenseRepository.captureDeferredLedgerBinding() == binding) {
                    val fallback = submissionFailureResources[row.type] ?: R.string.expense_correction_failed
                    _uiState.update { it.copy(message = error.toUiText(fallback), messageTone = MessageTone.Danger) }
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

    /** The command is already delivered; recovery only reads its authoritative result. */
    fun refreshExpense(row: OutboxRow) {
        if (_uiState.value.status.refreshRequired.none { it.id == row.id }) return
        val binding = expenseRepository.captureDeferredLedgerBinding() ?: return
        val id = parseExpenseTargetRef(row.targetId)?.toLongOrNull() ?: return
        resolve(row) {
            expenseRepository.fetchExpense(id).onFailure { error ->
                if (expenseRepository.captureDeferredLedgerBinding() == binding) {
                    _uiState.update { it.copy(message = error.toUiText(R.string.sync_status_refresh_failed),
                        messageTone = MessageTone.Danger) }
                }
            }
        }
    }

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
    val billSplitCreations: Map<Long, com.ticketbox.data.repository.PendingBillSplitCreation> = emptyMap(),
    val failedDebtCreations: Map<Long, PendingDebtCreation> = emptyMap(),
    val recurringOccurrences: Map<Long, com.ticketbox.data.repository.PendingOccurrencePayment> = emptyMap(),
    val incomeSubmissions: Map<Long, com.ticketbox.data.repository.PendingIncomePlanSubmission> = emptyMap(),
    val manualRates: Map<Long, com.ticketbox.data.repository.PendingManualRateSubmission> = emptyMap(),
    val manualCreations: Map<Long, com.ticketbox.data.repository.ManualExpenseCreationProjection> = emptyMap(),
    val goalEdits: Map<Long, com.ticketbox.data.repository.PendingGoalEdit> = emptyMap(),
    val goalCreations: Map<Long, com.ticketbox.data.repository.PendingGoalCreation> = emptyMap(),
    val budgetSaves: Map<Long, com.ticketbox.data.repository.PendingBudgetSave> = emptyMap(),
    val recurringItems: Map<Long, com.ticketbox.data.repository.RecurringPendingIntent> = emptyMap(),
    val categoryRules: Map<Long, com.ticketbox.data.repository.PendingCategoryRuleSubmission> = emptyMap(),
    val debtWrites: Map<Long, com.ticketbox.data.repository.PendingDebtWrite> = emptyMap(),
    val waitingDebtWrites: List<com.ticketbox.data.repository.PendingDebtWrite> = emptyList(),
    val retryableOffsetIds: Set<Long> = emptySet(),
    val busyRowId: Long? = null,
    val isClearingQuarantine: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
) {
    fun offersRetry(row: OutboxRow): Boolean {
        if (row.type in writerSubmissionTypes && correctionObservation.access?.canModify != true) return false
        return when (row.type) {
            in categoryRuleSubmissionTypes -> categoryRules[row.id]?.canRetry == true
            PendingMutationType.CreateRecurringItem, PendingMutationType.UpdateRecurringItem ->
                recurringItems[row.id]?.canRetry == true
            PendingMutationType.SetRecurringOccurrencePayment ->
                recurringOccurrences[row.id]?.canRetry == true
            PendingMutationType.SaveMonthlyBudget -> budgetSaves[row.id]?.canRetry == true
            PendingMutationType.SaveManualExchangeRate -> manualRates[row.id]?.canRetry == true
            in incomePlanSubmissionTypes -> incomeSubmissions[row.id]?.canRetry == true
            PendingMutationType.UpdateGoal -> goalEdits[row.id]?.canRetry == true
            PendingMutationType.CreateGoal -> goalCreations[row.id]?.canRetry == true
            in DEBT_WRITE_TYPES -> debtWrites[row.id]?.canRetry == true
            PendingMutationType.CreateExpenseOffset -> row.id in retryableOffsetIds
            else -> !row.requiresManualCreateReview()
        }
    }
}

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
    val debtWrites: com.ticketbox.data.repository.DebtWriteActions,
    val goalEdits: com.ticketbox.data.repository.GoalEditActions,
    val budgetSaves: com.ticketbox.data.repository.BudgetActions,
    val recurringItems: com.ticketbox.data.repository.RecurringManualMutationActions,
    val rules: com.ticketbox.data.repository.RuleRepository,
)

/** Route plan submissions to their existing command owner, including original-intent validation. */
private suspend fun OutboxRecoveryRepositories.recoverPlanningSubmission(
    binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean,
): Result<Unit>? = when (row.type) {
    in incomePlanSubmissionTypes -> incomePlans.describeSubmission(row)?.let {
        incomePlans.recoverSubmission(binding, it, drop)
    } ?: Result.failure(IllegalStateException())
    in categoryRuleSubmissionTypes -> rules.describeSubmission(row)?.let {
        rules.recoverSubmission(binding, it, drop)
    } ?: Result.failure(IllegalStateException())
    PendingMutationType.CreateGoal, PendingMutationType.UpdateGoal -> recoverGoalSubmission(binding, row, drop)
    PendingMutationType.SaveMonthlyBudget, PendingMutationType.SaveManualExchangeRate -> recoverBudgetSubmission(binding, row, drop)
    PendingMutationType.CreateRecurringItem, PendingMutationType.UpdateRecurringItem ->
        recurringItems.recoverManualIntent(binding, row, drop)
    PendingMutationType.SetRecurringOccurrencePayment ->
        recurringOccurrences?.recover(binding, row, drop) ?: Result.failure(IllegalStateException())
    else -> null
}

private suspend fun OutboxRecoveryRepositories.recoverGoalSubmission(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit> =
    if (row.type == PendingMutationType.CreateGoal) goalEdits.describeCreation(row)?.let { goalEdits.recoverCreation(binding, it, drop) }
        ?: Result.failure(IllegalStateException())
    else goalEdits.describeEdit(row)?.let { goalEdits.recover(binding, it, drop) } ?: Result.failure(IllegalStateException())

private suspend fun OutboxRecoveryRepositories.recoverBudgetSubmission(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit> =
    if (row.type == PendingMutationType.SaveMonthlyBudget) budgetSaves.describeSave(row)?.let { budgetSaves.recoverSave(binding, it, drop) }
        ?: Result.failure(IllegalStateException())
    else budgetSaves.describeRate(row)?.let { budgetSaves.recoverRate(binding, it, drop) } ?: Result.failure(IllegalStateException())
