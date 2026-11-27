package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationDoneUpdate
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationTokenCascade
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import java.time.Clock
import java.util.UUID

private val RECURRING_AFFECTING_TYPES = setOf(
    PendingMutationType.ConfirmRecurringCandidate,
    PendingMutationType.CreateRecurringItem,
    PendingMutationType.UpdateRecurringItem,
    PendingMutationType.SetRecurringOccurrencePayment,
    PendingMutationType.PatchExpense,
    PendingMutationType.CorrectExpense,
    PendingMutationType.CreateExpense,
    PendingMutationType.AcceptBillSplitInvitation,
    PendingMutationType.ConfirmExpense,
    PendingMutationType.UndoExpense,
    PendingMutationType.CreateExpenseOffset,
    PendingMutationType.VoidExpenseOffset,
    PendingMutationType.ConfirmRepaymentDraft,
)

internal fun OutboxRow.affectsRecurringReads(): Boolean = type in RECURRING_AFFECTING_TYPES

private data class StatusResolutionOutcome(
    val changed: Boolean,
    val expired: Boolean = false,
)

internal class OutboxSettlementCoordinator(
    private val dao: PendingMutationDao,
    private val binding: OutboxBindingCoordinator,
    private val clock: Clock,
    private val onSchedulePending: () -> Unit,
    private val onRowsDeleted: suspend (Int) -> Unit,
) {
    var onDebtDispatchPreparing: suspend (OutboxRow) -> Unit = {}
    var onDebtDispatchFinished: suspend (OutboxRow, DispatchResult?) -> Unit = { _, _ -> }
    var onDebtAccepted: suspend (OutboxRow) -> Unit = {}

    var onRecurringDispatchPreparing: suspend (OutboxRow) -> Unit = {}
    var onRecurringDispatchFinished: suspend (OutboxRow, DispatchResult?) -> Unit = { _, _ -> }
    var onRecurringAccepted: suspend (OutboxRow) -> Unit = {}

    var onIncomeDispatchPreparing: suspend (OutboxRow) -> Unit = {}
    var onIncomeDispatchFinished: suspend (OutboxRow, DispatchResult?) -> Unit = { _, _ -> }
    var onIncomeAccepted: suspend (OutboxRow) -> Unit = {}

    suspend fun prepareReadProtection(row: OutboxRow) {
        val rollback = mutableListOf<suspend (OutboxRow, DispatchResult?) -> Unit>()
        try {
            if (row.affectsRecurringReads()) {
                onRecurringDispatchPreparing(row)
                rollback += onRecurringDispatchFinished
            }
            if (row.type in DEBT_QUERY_MUTATION_TYPES) {
                onDebtDispatchPreparing(row)
                rollback += onDebtDispatchFinished
            }
            if (row.type in INCOME_QUERY_MUTATION_TYPES) {
                onIncomeDispatchPreparing(row)
                rollback += onIncomeDispatchFinished
            }
        } catch (error: Throwable) {
            val unsent = DispatchResult.Failure("read_protection_prepare_failed", definitelyRejected = true)
            withContext(NonCancellable) {
                for (finish in rollback.asReversed()) runCatching { finish(row, unsent) }
            }
            throw error
        }
    }

    suspend fun finishReadProtection(row: OutboxRow, result: DispatchResult?) {
        if (row.affectsRecurringReads()) onRecurringDispatchFinished(row, result)
        if (row.type in DEBT_QUERY_MUTATION_TYPES) onDebtDispatchFinished(row, result)
        if (row.type in INCOME_QUERY_MUTATION_TYPES) onIncomeDispatchFinished(row, result)
    }

    suspend fun markDone(id: Long, settlement: OutboxDoneSettlement): Boolean {
        val acceptedRow = settlement.acceptedRow
        val refreshError = settlement.refreshError()
        val recurringAccepted = acceptedRow?.affectsRecurringReads() == true
        val debtAccepted = acceptedRow?.type in DEBT_QUERY_MUTATION_TYPES
        val incomeAccepted = acceptedRow?.type in INCOME_QUERY_MUTATION_TYPES
        return try {
            if (recurringAccepted) onRecurringAccepted(requireNotNull(acceptedRow))
            if (debtAccepted) onDebtAccepted(requireNotNull(acceptedRow))
            if (incomeAccepted) onIncomeAccepted(requireNotNull(acceptedRow))
            dao.markDoneAndCascadeToken(
                done = PendingMutationDoneUpdate(
                    id = id,
                    status = PendingMutationStatus.Done.wireValue,
                    completedAt = clock.outboxNowIso(),
                    lastError = refreshError,
                    receiptJson = settlement.receiptJson,
                ),
                cascade = settlement.tokenCascade(),
            ) > 0
        } catch (error: SQLiteException) {
            val diagnostic = acceptedReadPublicationDiagnostic(recurringAccepted, debtAccepted, incomeAccepted)
            if (diagnostic != null) {
                withContext(NonCancellable) {
                    dao.markRetryable(id, PendingMutationStatus.Pending.wireValue, diagnostic)
                }
            }
            throw error
        }
    }

    suspend fun recoverBudgetReadRefresh(
        bound: BoundLedgerRequest,
        month: String,
        cleanup: suspend (OutboxRow) -> Unit,
    ) = binding.withActiveBinding(bound) { current ->
        val rows = dao.activeRowsForTarget(current, monthlyBudgetTarget(month), listOf(PendingMutationStatus.Done.wireValue))
            .filter { it.requiresBudgetReadRefresh() }
        for (row in rows) {
            cleanup(row)
            dao.clearAcceptedReadRefresh(row.id, requireNotNull(row.receiptJson), BUDGET_READ_REFRESH_REQUIRED)
        }
    }

    suspend fun acknowledgeRuleApplicationRefresh(bound: BoundLedgerRequest, original: OutboxRow) =
        binding.withActiveBinding(bound) { current ->
            val persisted = dao.activeRowsForTarget(current, RULE_APPLICATION_TARGET, listOf(PendingMutationStatus.Done.wireValue))
                .firstOrNull { it.id == original.id }
            require(persisted == original && original.requiresRuleApplicationRefresh()) { "原应用状态已变化，请重新核对。" }
            check(dao.clearAcceptedReadRefresh(original.id, requireNotNull(original.receiptJson), RULE_APPLICATION_READ_REFRESH) == 1)
        }

    suspend fun acknowledgeExpenseRefresh(boundRequest: BoundLedgerRequest, versions: Map<Long, Long>) =
        binding.withBindingLock { current ->
            try {
                boundRequest.requireStillActiveFor(current)
            } catch (_: RepositoryException) {
                return@withBindingLock
            }
            dao.clearAdoptedExpenseRefreshes(current, versions)
        }

    suspend fun discardOriginalExpense(
        boundRequest: BoundLedgerRequest,
        row: OutboxRow,
        afterDeleted: suspend () -> Unit,
    ): Boolean = binding.withActiveBinding(boundRequest) { current ->
        check(
            row.type in setOf(PendingMutationType.CreateExpense, PendingMutationType.CorrectExpense) &&
                row.status in setOf(
                    PendingMutationStatus.Failed,
                    PendingMutationStatus.Conflict,
                    PendingMutationStatus.Done,
                    PendingMutationStatus.Pending,
                ),
        )
        check(row.type != PendingMutationType.CreateExpense || row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict))
        check(row.ownerKey == current.ownerStorageKey && row.ledgerId == current.ledgerId)
        dao.deleteAndPublish(row.id, current.ownerStorageKey, current.ledgerId, row.status.wireValue, afterDeleted)
    }.also { changed ->
        if (changed) {
            onSchedulePending()
            if (row.type == PendingMutationType.CreateExpense) onRowsDeleted(1)
        }
    }

    suspend fun recoverUploadGroup(
        boundRequest: BoundLedgerRequest,
        targetId: String,
        drop: Boolean,
        retryIds: List<Long>,
    ): Boolean {
        var retried = 0
        var removed = 0
        val changed = binding.withDispatchLease {
            binding.withActiveBinding(boundRequest) { current ->
                if (drop) {
                    removed = dao.deleteUnfinishedUploadGroup(current.ownerStorageKey, current.ledgerId, targetId)
                    removed > 0
                } else {
                    val eligible = dao.activeRowsForTarget(current, targetId, OutboxRepository.ACTIVE_STATUS_VALUES)
                        .filter { row ->
                            row.type == PendingMutationType.UploadScreenshot &&
                                row.status == PendingMutationStatus.Failed &&
                                row.id in retryIds
                        }
                    val (updated, retriedCount) = dao.retryEligibleUploadRows(
                        current,
                        eligible,
                        clock::outboxOverAgeCutoffIso,
                    )
                    retried = retriedCount
                    updated
                }
            }
        }
        if (retried > 0) onSchedulePending()
        onRowsDeleted(removed)
        return changed
    }

    suspend fun resolveStatus(
        id: Long,
        status: PendingMutationStatus,
        drop: Boolean,
        freshToken: Long?,
        boundRequest: BoundLedgerRequest?,
    ): Boolean {
        val outcome = binding.withBindingLock { current ->
            boundRequest?.requireStillActiveFor(current)
            if (drop) {
                StatusResolutionOutcome(
                    changed = dao.deleteIfStatus(id, current.ownerStorageKey, current.ledgerId, status.wireValue) > 0,
                )
            } else {
                applyRetryResolutionLocked(current, id, status, freshToken)
            }
        }
        if (outcome.changed && !outcome.expired) onSchedulePending()
        if (outcome.changed && drop) onRowsDeleted(1)
        return outcome.changed
    }

    private suspend fun applyRetryResolutionLocked(
        current: OutboxBinding,
        id: Long,
        status: PendingMutationStatus,
        freshToken: Long?,
    ): StatusResolutionOutcome {
        if (dao.refusesExpenseRecovery(current, id, status, freshToken)) {
            return StatusResolutionOutcome(changed = false)
        }
        if (dao.expireBoundIfOverAge(id, current, status.wireValue, clock.outboxOverAgeCutoffIso())) {
            val expired = freshToken != null ||
                status != PendingMutationStatus.Failed ||
                dao.retryFailed(id, current.ownerStorageKey, current.ledgerId, NON_RETRYABLE_UPLOAD_ERRORS) == 0
            return StatusResolutionOutcome(changed = true, expired = expired)
        }
        if (freshToken != null) {
            val requeue = if (status == PendingMutationStatus.Conflict) {
                dao::requeueConflictWithFreshToken
            } else {
                dao::requeueFailedWithFreshToken
            }
            val updated = requeue(id, current.ownerStorageKey, current.ledgerId, freshToken, UUID.randomUUID().toString()) > 0
            return StatusResolutionOutcome(changed = updated)
        }
        val retried = dao.retryFailed(id, current.ownerStorageKey, current.ledgerId, NON_RETRYABLE_UPLOAD_ERRORS) > 0
        return StatusResolutionOutcome(changed = retried)
    }
}

internal data class OutboxDoneSettlement(
    val cacheRefreshVersion: Long? = null,
    val receiptJson: String? = null,
    val acceptedReadRefreshRequired: Boolean = false,
    val acceptedRow: OutboxRow? = null,
    val cascadeNewToken: Long? = null,
) {
    fun refreshError(): String? = if (acceptedReadRefreshRequired) {
        mapOf(
            PendingMutationType.SaveMonthlyBudget to BUDGET_READ_REFRESH_REQUIRED,
            PendingMutationType.ApplyConfirmedRules to RULE_APPLICATION_READ_REFRESH,
        ).getValue(requireNotNull(acceptedRow).type)
    } else {
        cacheRefreshVersion?.let { "$EXPENSE_REFRESH_PREFIX$it" }
    }

    fun tokenCascade(): PendingMutationTokenCascade? {
        val token = cascadeNewToken?.takeIf { it > 0L } ?: return null
        val row = acceptedRow ?: return null
        val ownerKey = row.ownerKey?.takeIf(String::isNotBlank) ?: return null
        return preservedTokenCascade(ownerKey, row.ledgerId, row.targetId, token)
    }
}

private fun acceptedReadPublicationDiagnostic(
    recurringAccepted: Boolean,
    debtAccepted: Boolean,
    incomeAccepted: Boolean,
): String? = when {
    recurringAccepted -> "accepted_recurring_read_publication_pending"
    debtAccepted -> "accepted_debt_read_publication_pending"
    incomeAccepted -> "accepted_income_read_publication_pending"
    else -> null
}
