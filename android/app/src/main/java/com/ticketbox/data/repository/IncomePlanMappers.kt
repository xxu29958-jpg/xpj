package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType

fun IncomePlanDto.toDomain(): IncomePlan = IncomePlan(
    publicId = publicId,
    label = label,
    sourceType = IncomeSourceType.fromWire(sourceType),
    amountCents = amountCents,
    payDay = payDay,
    status = IncomePlanStatus.fromWire(status),
    createdAt = createdAt,
    updatedAt = updatedAt,
    archivedAt = archivedAt,
)

data class IncomePlanDraft(
    val label: String,
    val sourceType: IncomeSourceType,
    val amountCents: Long,
    val payDay: Int,
)

fun IncomePlanDraft.toCreateRequest(): IncomePlanCreateRequestDto =
    IncomePlanCreateRequestDto(
        label = label.trim(),
        sourceType = sourceType.wireValue,
        amountCents = amountCents,
        payDay = payDay,
    )

data class IncomePlanPatch(
    val expectedUpdatedAt: String,
    val label: String? = null,
    val sourceType: IncomeSourceType? = null,
    val amountCents: Long? = null,
    val payDay: Int? = null,
)

fun IncomePlanPatch.toUpdateRequest(): IncomePlanUpdateRequestDto =
    IncomePlanUpdateRequestDto(
        expectedUpdatedAt = expectedUpdatedAt,
        label = label?.trim(),
        sourceType = sourceType?.wireValue,
        amountCents = amountCents,
        payDay = payDay,
    )
