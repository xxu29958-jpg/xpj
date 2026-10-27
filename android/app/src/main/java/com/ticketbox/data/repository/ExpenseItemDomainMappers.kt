package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseItemRequestDto
import com.ticketbox.domain.model.ExpenseItemDraft

internal fun ExpenseItemRequestDto.toDomain(): ExpenseItemDraft = ExpenseItemDraft(
    name = name,
    kind = kind,
    quantityText = quantityText,
    unitPriceCents = unitPriceCents,
    amountCents = amountCents,
    category = category,
    rawText = rawText,
    confidence = confidence,
)
