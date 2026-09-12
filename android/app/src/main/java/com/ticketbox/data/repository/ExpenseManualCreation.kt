package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.data.local.PendingMutationType
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Manual entry admission. All commands still use the existing atomic Room/Outbox create. */
internal class ExpenseManualCreation(private val core: ExpenseRepositoryCore) {
    private val admission = Mutex()

    suspend fun create(draft: ExpenseDraft): Result<Expense> = core.errorHandler.safeCall {
        check(core.canModifyLedger()) { "当前账本没有编辑权限。" }
        require(draft.amountCents != null || draft.originalAmountMinor != null) { "请先填写金额。" }
        core.enqueueLocalCreate(core.ledgerRequestGuard.bind(), draft, UUID.randomUUID().toString())
    }

    suspend fun isSaved(binding: LogicalSessionBinding, clientRef: String): Result<Boolean> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        val saved = observe(clientRef).first() != null
        bound.requireStillActive()
        saved
    }

    /** Restored navigation adopts the original acceptance; a changed draft cannot replace a published command. */
    suspend fun create(draft: ExpenseDraft, binding: LogicalSessionBinding, clientRef: String): Result<Unit> = core.errorHandler.safeCall {
        admission.withLock {
            require(clientRef.isNotBlank())
            val bound = core.ledgerRequestGuard.bindExact(binding)
            if (observe(clientRef).first() == null) {
                check(core.canModifyLedger()) { "当前账本没有编辑权限。" }
                require(draft.amountCents != null || draft.originalAmountMinor != null) { "请先填写金额。" }
                core.enqueueLocalCreate(bound, draft, clientRef)
            }
            bound.requireStillActive()
        }
    }

    fun observe(clientRef: String): Flow<ManualExpenseCreationProjection?> = core.offlineMutations.outbox
        .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true).map { rows ->
            rows.singleOrNull { it.targetId == expenseLocalTargetId(clientRef) }?.let { core.describeManualCreation(it) }
        }
}
