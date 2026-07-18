package com.ticketbox.data.repository

import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.LedgerSummary

interface BillSplitActions {
    fun canModifyLedger(): Boolean = true

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
