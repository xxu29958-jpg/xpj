package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtActivityListDto
import com.ticketbox.domain.model.DebtActivity
import com.ticketbox.domain.model.DebtActivityPage

/** Complete participant history through the same bound read authority as the Debt detail. */
class DebtActivityRepository internal constructor(private val reader: DebtQueryReader) : DebtActivityQueries {
    override fun observeReadAccessDenials() = reader.readAccessDenials
    override fun observeResourceDenials() = reader.readResourceDenials
    override suspend fun listActivity(task: DebtTask, page: Int, focusRepayment: String?): Result<ReadSnapshot<DebtActivityPage>> =
        reader.activity(task, page, focusRepayment)
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
