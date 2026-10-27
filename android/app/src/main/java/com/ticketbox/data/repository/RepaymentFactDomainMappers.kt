package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RepaymentFactListDto
import com.ticketbox.domain.model.RepaymentFactList



internal fun RepaymentFactListDto.toDomain(): RepaymentFactList = RepaymentFactList(
    homeCurrencyCode = homeCurrencyCode,
    items = items.map { it.toDomain() },
)


