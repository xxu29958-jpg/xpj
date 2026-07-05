package com.ticketbox.viewmodel

import com.ticketbox.data.repository.BillSplitActions
import com.ticketbox.data.repository.BillSplitLedgerActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
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
    override suspend fun fetchBillSplitInbox(): Result<List<BillSplitInbox>> =
        repository.fetchBillSplitInbox()

    override suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>> =
        repository.fetchBillSplitSent()

    override suspend fun acceptBillSplitInvitation(
        publicId: String,
        targetLedgerId: String,
    ): Result<BillSplitInbox> = repository.acceptBillSplitInvitation(publicId, targetLedgerId)

    override suspend fun rejectBillSplitInvitation(publicId: String): Result<BillSplitInbox> =
        repository.rejectBillSplitInvitation(publicId)

    override suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent> =
        repository.cancelBillSplitInvitation(publicId)
}

private class LedgerRepositoryBillSplitActions(
    private val repository: LedgerRepository,
) : BillSplitLedgerActions {
    override fun cachedLedgers(): List<LedgerSummary> = repository.cachedLedgers()

    override suspend fun refreshLedgers(): Result<List<LedgerSummary>> =
        repository.refreshLedgers()
}
