package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseItemDto
import com.ticketbox.data.remote.dto.ExpenseItemRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.domain.model.ExpenseItem
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.normalizeExpenseCategory

fun ExpenseItemsResponseDto.toDomain(): ExpenseItems = ExpenseItems(
    expenseId = expenseId,
    parentAmountCents = parentAmountCents,
    itemsTotalAmountCents = itemsTotalAmountCents,
    mismatchCents = mismatchCents,
    items = items.map { it.toDomain() },
)

fun ExpenseItemDto.toDomain(): ExpenseItem = ExpenseItem(
    publicId = publicId,
    position = position,
    name = name,
    quantityText = quantityText,
    unitPriceCents = unitPriceCents,
    amountCents = amountCents,
    category = normalizeExpenseCategory(category),
    rawText = rawText,
    confidence = confidence,
    isOcrDraft = isOcrDraft,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

fun ExpenseItemDraft.toRequest(): ExpenseItemRequestDto {
    val cleanName = name.trim()
    if (cleanName.isBlank()) {
        throw RepositoryException("请输入商品名称。")
    }
    return ExpenseItemRequestDto(
        name = cleanName,
        quantityText = quantityText.cleanOptional(),
        unitPriceCents = unitPriceCents,
        amountCents = amountCents,
        category = category.cleanOptional()?.let(::normalizeExpenseCategory),
        rawText = rawText.cleanOptional(),
        confidence = confidence,
    )
}
