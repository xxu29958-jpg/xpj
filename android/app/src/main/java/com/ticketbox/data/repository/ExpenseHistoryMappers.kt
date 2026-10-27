package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import com.ticketbox.data.remote.dto.ExpenseRevisionPageDto
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.ExpenseRevisionPage

fun ExpenseRevisionDto.toDomain(): ExpenseRevision = ExpenseRevision(
    publicId = publicId,
    revisionNumber = revisionNumber,
    changeKind = changeKind,
    reason = reason,
    changedFields = changedFields,
    before = before,
    after = after,
    actorAccountName = actorAccountName,
    actorDeviceName = actorDeviceName,
    createdAt = createdAt,
    offsetPublicId = offsetPublicId,
)

fun ExpenseRevisionPageDto.toDomain(): ExpenseRevisionPage = ExpenseRevisionPage(
    items = items.map(ExpenseRevisionDto::toDomain),
    page = page,
    pageSize = pageSize,
    total = total,
    snapshotRevision = snapshotRevision,
    offsetSnapshotId = requireNotNull(offsetSnapshotId),
)

