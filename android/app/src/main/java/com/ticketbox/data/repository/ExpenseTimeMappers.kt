package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.remote.dto.ExpenseAccountingTimeDto
import com.ticketbox.data.remote.dto.ExpenseTimeInputDto
import com.ticketbox.domain.model.ExpenseAccountingTime
import com.ticketbox.domain.model.ExpenseTimeInput

internal fun ExpenseAccountingTimeDto.toDomain(): ExpenseAccountingTime = ExpenseAccountingTime(
    precision, instantUtc, userLocalDate, sourceTimezone, sourceUtcOffsetSeconds, accountingDate, calendarRevision, basis,
)

internal fun ExpenseEntity.accountingTime(): ExpenseAccountingTime? = timePrecision?.let { precision ->
    ExpenseAccountingTime(precision, timeInstantUtc, userLocalDate, sourceTimezone,
        sourceUtcOffsetSeconds, accountingDate, calendarRevision, accountingDateBasis)
}

fun ExpenseTimeInput.toRequest(): ExpenseTimeInputDto = ExpenseTimeInputDto(
    precision, calendarRevision, userLocalDate, instantUtc, sourceTimezone, sourceUtcOffsetSeconds, accountingDate,
)

internal fun ExpenseTimeInput.toCapturedTime(): ExpenseAccountingTime = ExpenseAccountingTime(
    precision, instantUtc, userLocalDate, sourceTimezone, sourceUtcOffsetSeconds, accountingDate, calendarRevision,
)

internal fun ExpenseTimeInput.matches(evidence: ExpenseAccountingTime?): Boolean = evidence != null &&
    precision == evidence.precision && calendarRevision == evidence.calendarRevision &&
    userLocalDate == evidence.userLocalDate && instantUtc == evidence.instantUtc &&
    sourceTimezone == evidence.sourceTimezone && sourceUtcOffsetSeconds == evidence.sourceUtcOffsetSeconds &&
    (accountingDate == null || accountingDate == evidence.accountingDate)
