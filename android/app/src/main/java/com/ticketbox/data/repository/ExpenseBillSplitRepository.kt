package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitInviteRequestDto
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent

internal class ExpenseBillSplitRepository(
    private val core: ExpenseRepositoryCore,
) {
    suspend fun createBillSplitInvitation(
        expenseId: Long,
        receiverAccountId: Long,
        amountCents: Long,
    ): Result<BillSplitSent> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        bound.call {
            it.createBillSplitInvitation(
                expenseId,
                BillSplitInviteRequestDto(receiverAccountId, amountCents),
            )
        }.toDomain()
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
