package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtActivityListDto
import com.ticketbox.domain.model.DebtActivity
import com.ticketbox.domain.model.DebtActivityPage

/** Complete participant history through the same bound read authority as the Debt detail. */
class DebtActivityRepository(apiProvider: ApiServiceProvider) : DebtActivityQueries {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "DebtActivity",
        statusMessages = mapOf(403 to "当前账号无法查看这笔往来的历史。", 404 to "没有找到这笔欠款。"),
    )

    override suspend fun listActivity(task: DebtTask, page: Int, focusRepayment: String?): Result<DebtActivityPage> =
        errors.safeCall {
            guard.bindExact(task.binding).call { api ->
                api.debtActivity(task.debtPublicId, page, focusRepayment).toDomain()
            }
        }
}

internal fun DebtActivityListDto.toDomain() = DebtActivityPage(
    debtPublicId, homeCurrencyCode,
    items.map { DebtActivity(it.kind, it.publicId, it.recordedAt, it.actorDisplayName, it.actorIsYou,
        it.amountCents, it.reason, it.repayment?.toDomain(), it.proposal?.toDomain(), it.splitChange?.let { change ->
            com.ticketbox.domain.model.DebtSplitChange(change.status, change.shareBeforeAmountCents,
                change.newShareAmountCents, change.settlementNetAmountCents, change.originalPaidAmountCents,
                change.returnPaidAmountCents, change.originalForgivenAmountCents, change.returnForgivenAmountCents,
                change.reason)
        }) },
    page, pageSize, total,
)
