package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseSplitRequestDto
import com.ticketbox.domain.model.ExpenseSplitDraft

internal fun ExpenseSplitRequestDto.toDomain(): ExpenseSplitDraft = ExpenseSplitDraft(
    memberId = memberId,
    amountCents = amountCents,
    note = note,
)
