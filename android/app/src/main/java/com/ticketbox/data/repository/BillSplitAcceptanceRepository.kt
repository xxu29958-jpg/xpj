package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.squareup.moshi.JsonDataException
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

/** Receiver publication and recovery share this owner across Inbox and Sync. */
internal class BillSplitAcceptanceRepository(private val core: ExpenseRepositoryCore) {
    private val outbox = core.offlineMutations.outbox
    private val acceptAdapter = core.offlineMutations.billSplitAcceptAdapter

    suspend fun acceptBillSplitInvitation(binding: LogicalSessionBinding, original: BillSplitAcceptPayload): Result<Long> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        require(original.revision == 1 && original.publicId.isNotBlank() && original.targetLedgerId.isNotBlank() &&
            original.amountCents > 0 && CurrencyCode.fromStorageKeyOrNull(original.homeCurrencyCode) != null) { "请先核对原邀请和目标账本。" }
        // The active ledger may be read-only. The command owner checks the chosen target's current writer permission.
        outbox.enqueueOriginalCreation(bound, PendingMutationIntent(PendingMutationType.AcceptBillSplitInvitation,
            "bill-split:${original.publicId}", acceptAdapter.toJson(original), 0L, original.publicId))
    }

    fun describeAcceptance(row: OutboxRow): PendingBillSplitAcceptance? {
        val binding = core.ledgerRequestGuard.captureLogicalBinding() ?: return null
        if (row.type != PendingMutationType.AcceptBillSplitInvitation || row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId) return null
        val original = acceptAdapter.readAcceptance(row)
        val receipt = row.receiptJson?.let { json -> try {
            core.offlineMutations.billSplitAcceptedAdapter.fromJson(json)?.takeIf { original != null && it.accepts(original) }?.toDomain()
        } catch (_: JsonDataException) { null } catch (_: IOException) { null } }
        return PendingBillSplitAcceptance(row, original, receipt)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    fun observeAcceptances(): Flow<BillSplitAcceptanceObservation> = core.apiProvider.observeActiveLedgerAccess().flatMapLatest { access ->
        if (access == null) flowOf(BillSplitAcceptanceObservation(null))
        else outbox.observeActiveByTypes(setOf(PendingMutationType.AcceptBillSplitInvitation), includeCompleted = true).map { rows ->
            if (core.ledgerRequestGuard.captureLogicalBinding() != access.binding) BillSplitAcceptanceObservation(null)
            else BillSplitAcceptanceObservation(access, rows.mapNotNull(::describeAcceptance))
        }
    }

    suspend fun recoverAcceptance(binding: LogicalSessionBinding, id: Long, drop: Boolean): Result<Unit> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        val current = observeAcceptances().first()
        val original = current.submissions.singleOrNull { it.row.id == id }
        bound.requireStillActive()
        if (current.access?.binding != binding || original == null || original.row.status != PendingMutationStatus.Failed ||
            (!drop && !original.canRetry)) throw RepositoryException("请核对原接受任务后继续。")
        if (!outbox.resolveFailed(id, if (drop) FailedResolution.Drop else FailedResolution.Retry(), boundRequest = bound)) {
            throw RepositoryException("原接受任务已变化，请重新查看。")
        }
    }

}
