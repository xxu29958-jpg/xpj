package com.ticketbox.viewmodel

import com.ticketbox.data.repository.BillSplitActions
import com.ticketbox.data.repository.BillSplitLedgerActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.flow.Flow
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.LedgerSummary

internal fun expenseBillSplitActions(repository: ExpenseRepository): BillSplitActions =
    ExpenseRepositoryBillSplitActions(repository)

internal fun ledgerBillSplitActions(repository: LedgerRepository): BillSplitLedgerActions =
    LedgerRepositoryBillSplitActions(repository)

private class ExpenseRepositoryBillSplitActions(
    private val repository: ExpenseRepository,
) : BillSplitActions {
    override fun currentAccess(): LedgerAccessContext? = repository.captureDeferredLedgerBinding()?.let {
        LedgerAccessContext(it, repository.canModifyLedger())
    }

    override fun observeAccess(): Flow<LedgerAccessContext?> = repository.observeLedgerAccess()

    override suspend fun fetchBillSplitInbox(binding: LogicalSessionBinding): Result<List<BillSplitInbox>> =
        repository.fetchBillSplitInbox(binding)

    override suspend fun fetchBillSplitSent(binding: LogicalSessionBinding): Result<List<BillSplitSent>> =
        repository.fetchBillSplitSent(binding)

    override suspend fun acceptBillSplitInvitation(
        binding: LogicalSessionBinding,
        publicId: String,
        targetLedgerId: String,
    ): Result<BillSplitInbox> = repository.acceptBillSplitInvitation(binding, publicId, targetLedgerId)

    override suspend fun rejectBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitInbox> =
        repository.rejectBillSplitInvitation(binding, publicId)

    override suspend fun cancelBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitSent> =
        repository.cancelBillSplitInvitation(binding, publicId)
}

private class LedgerRepositoryBillSplitActions(
    private val repository: LedgerRepository,
) : BillSplitLedgerActions {
    override fun cachedLedgers(): List<LedgerSummary> = repository.cachedLedgers()

    override suspend fun refreshLedgers(): Result<List<LedgerSummary>> =
        repository.refreshLedgers()
}
