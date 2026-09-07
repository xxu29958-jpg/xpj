package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitInviteRequestDto
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.Expense
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import java.util.UUID
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

internal class ExpenseBillSplitRepository(
    private val core: ExpenseRepositoryCore,
) {
    private val outbox = core.offlineMutations.outbox
    private val adapter = core.offlineMutations.billSplitCreateAdapter

    fun describeCreation(row: OutboxRow): PendingBillSplitCreation? {
        val binding = core.ledgerRequestGuard.captureLogicalBinding() ?: return null
        if (row.type != PendingMutationType.CreateBillSplitInvitation || row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId) return null
        val receipt = row.receiptJson?.let { json -> runCatching {
            core.offlineMutations.billSplitReceiptAdapter.fromJson(json)?.toDomain()
        }.getOrNull() }
        return PendingBillSplitCreation(row, adapter.readBillSplitIntent(row), receipt)
    }

    suspend fun createBillSplitInvitation(
        expectedBinding: LogicalSessionBinding,
        expense: Expense,
        receiverAccountId: Long,
        receiverName: String,
        amountCents: Long,
    ): Result<Long> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) throw RepositoryException("当前角色为只读，无法修改账本。")
        val bound = core.ledgerRequestGuard.bindExact(expectedBinding)
        if (expense.id <= 0 || expense.rowVersion <= 0 || expense.status != "confirmed" || expense.pendingSync) {
            throw RepositoryException("请先核对已确认账单。")
        }
        val currency = expense.homeCurrencyCode ?: throw RepositoryException("账单币种不可核对。")
        val payload = BillSplitCreatePayload(1, expense.id, expense.merchant, receiverName, currency,
            BillSplitInviteRequestDto(receiverAccountId, amountCents, expense.rowVersion))
        outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
            type = PendingMutationType.CreateBillSplitInvitation, targetId = "expense:${expense.id}",
            payloadJson = adapter.toJson(payload), expectedRowVersion = expense.rowVersion,
            idempotencyKey = UUID.randomUUID().toString()), validateTargetRows = { rows ->
                if (rows.any { it.status != PendingMutationStatus.Done }) {
                    throw RepositoryException("这笔账单有待处理的提交，请先查看原提交。")
                }
            })
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    fun observeCreations(): Flow<BillSplitCreationObservation> = core.apiProvider.observeActiveLedgerAccess().flatMapLatest { access ->
        if (access == null) flowOf(BillSplitCreationObservation(null))
        else outbox.observeActiveByTypes(setOf(PendingMutationType.CreateBillSplitInvitation), includeCompleted = true).map { rows ->
            if (core.ledgerRequestGuard.captureLogicalBinding() != access.binding) BillSplitCreationObservation(null)
            else BillSplitCreationObservation(access, rows.mapNotNull(::describeCreation))
        }
    }

    suspend fun recover(expectedBinding: LogicalSessionBinding, id: Long, drop: Boolean): Result<Unit> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(expectedBinding)
        val current = observeCreations().first()
        if (current.access?.binding != expectedBinding) throw RepositoryException("账本连接已变化，请重新查看。")
        val pending = current.submissions.singleOrNull { it.row.id == id } ?: throw RepositoryException("原提交状态已变化。")
        bound.requireStillActive()
        if (pending.row.status != PendingMutationStatus.Failed || (!drop && (!pending.canRetry || current.access?.canModify != true))) {
            throw RepositoryException("请核对原提交后继续。")
        }
        if (!outbox.resolveFailed(id, if (drop) FailedResolution.Drop else FailedResolution.Retry(), boundRequest = bound)) {
            throw RepositoryException("原提交状态已变化，请重新查看。")
        }
    }

    suspend fun fetchBillSplitInbox(): Result<List<BillSplitInbox>> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.listBillSplitInbox() }.items.map { it.toDomain() }
    }

    suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.listBillSplitSent() }.items.map { it.toDomain() }
    }

    suspend fun acceptBillSplitInvitation(
        publicId: String,
        targetLedgerId: String,
    ): Result<BillSplitInbox> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call {
            it.acceptBillSplitInvitation(
                publicId,
                BillSplitAcceptRequestDto(targetLedgerId),
            )
        }.toDomain()
    }

    suspend fun rejectBillSplitInvitation(publicId: String): Result<BillSplitInbox> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.rejectBillSplitInvitation(publicId) }.toDomain()
    }

    suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.cancelBillSplitInvitation(publicId) }.toDomain()
    }
}
