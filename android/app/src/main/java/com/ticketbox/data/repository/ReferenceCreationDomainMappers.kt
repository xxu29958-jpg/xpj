package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ReferenceCreatedDto
import com.ticketbox.domain.model.ReferenceCreated

internal fun ReferenceCreatedDto.toDomain(): ReferenceCreated = ReferenceCreated(
    kind = kind,
    publicId = publicId,
    name = name,
    rowVersion = rowVersion,
)
