package com.ticketbox.viewmodel

import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.IncomeHistoryPage

/** Creation, editing and listing fixtures must not accidentally request revision history. */
internal abstract class IncomePlanTestActions : IncomePlanActions {
    override suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?):
        Result<com.ticketbox.data.repository.ReadSnapshot<IncomeHistoryPage>> = error("History is not requested in this fixture")
}
