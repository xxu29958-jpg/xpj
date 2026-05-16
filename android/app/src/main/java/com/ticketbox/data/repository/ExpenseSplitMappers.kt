package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseSplitDto
import com.ticketbox.data.remote.dto.ExpenseSplitRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.domain.model.ExpenseSplit
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits

fun ExpenseSplitsResponseDto.toDomain(): ExpenseSplits = ExpenseSplits(
    expenseId = expenseId,
    parentAmountCents = parentAmountCents,
    splitsTotalAmountCents = splitsTotalAmountCents,
    mismatchCents = mismatchCents,
    splits = splits.map { it.toDomain() },
)

fun ExpenseSplitDto.toDomain(): ExpenseSplit = ExpenseSplit(
    publicId = publicId,
    position = position,
    memberId = memberId,
    accountName = accountName,
    role = role,
    amountCents = amountCents,
    note = note,
    disabledAt = disabledAt,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

fun ExpenseSplitDraft.toRequest(): ExpenseSplitRequestDto {
    if (memberId <= 0L) {
        throw RepositoryException("请选择拆账成员。")
    }
    if (amountCents < 0L) {
        throw RepositoryException("拆账金额不能为负数。")
    }
    return ExpenseSplitRequestDto(
        memberId = memberId,
        amountCents = amountCents,
        note = note.cleanOptional(),
    )
}
