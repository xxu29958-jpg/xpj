package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.flow.Flow
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.LedgerSummary

interface BillSplitActions {
    suspend fun fetchBillSplitInbox(): Result<List<BillSplitInbox>>

    suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>>

    suspend fun acceptBillSplitInvitation(
        publicId: String,
        targetLedgerId: String,
    ): Result<BillSplitInbox>

    suspend fun rejectBillSplitInvitation(publicId: String): Result<BillSplitInbox>

    suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent>
}

interface BillSplitLedgerActions {
    fun cachedLedgers(): List<LedgerSummary>

    suspend fun refreshLedgers(): Result<List<LedgerSummary>>
}

/** Sender fact consumer: original publication, its recovery, and canonical sent invitations. */
interface BillSplitSourceActions {
    fun observeBillSplitCreations(): Flow<BillSplitCreationObservation>
    suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>>
    suspend fun createBillSplitInvitation(
        expectedBinding: LogicalSessionBinding,
        expense: Expense,
        receiverAccountId: Long,
        receiverName: String,
        amountCents: Long,
    ): Result<Long>
    suspend fun recoverBillSplitCreation(expectedBinding: LogicalSessionBinding, id: Long, drop: Boolean): Result<Unit>
    suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent>
}
