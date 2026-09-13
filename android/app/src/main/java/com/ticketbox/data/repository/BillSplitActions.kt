package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.flow.Flow
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.LedgerSummary

interface BillSplitActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeAccess(): Flow<LedgerAccessContext?>
    suspend fun fetchBillSplitInbox(binding: LogicalSessionBinding): Result<List<BillSplitInbox>>

    suspend fun fetchBillSplitSent(binding: LogicalSessionBinding): Result<List<BillSplitSent>>

    suspend fun acceptBillSplitInvitation(
        binding: LogicalSessionBinding,
        publicId: String,
        targetLedgerId: String,
    ): Result<BillSplitInbox>

    suspend fun rejectBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitInbox>

    suspend fun cancelBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitSent>
}

interface BillSplitLedgerActions {
    fun cachedLedgers(): List<LedgerSummary>

    suspend fun refreshLedgers(): Result<List<LedgerSummary>>
}

/** Sender fact consumer: original publication, its recovery, and canonical sent invitations. */
interface BillSplitSourceActions {
    fun observeBillSplitCreations(): Flow<BillSplitCreationObservation>
    suspend fun fetchBillSplitSent(binding: LogicalSessionBinding): Result<List<BillSplitSent>>
    suspend fun createBillSplitInvitation(
        expectedBinding: LogicalSessionBinding,
        expense: Expense,
        receiverAccountId: Long,
        receiverName: String,
        amountCents: Long,
    ): Result<Long>
    suspend fun recoverBillSplitCreation(expectedBinding: LogicalSessionBinding, id: Long, drop: Boolean): Result<Unit>
    suspend fun cancelBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitSent>
}
