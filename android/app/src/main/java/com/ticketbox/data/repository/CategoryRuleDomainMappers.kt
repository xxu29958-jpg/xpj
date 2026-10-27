package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.domain.model.CategoryRuleDefinition

internal fun CategoryRuleRequest.toDomain(): CategoryRuleDefinition = CategoryRuleDefinition(
    keyword = keyword,
    category = category,
    enabled = enabled,
    priority = priority,
    amountMinCents = amountMinCents,
    amountMaxCents = amountMaxCents,
    sourceContains = sourceContains,
    tagContains = tagContains,
    homeCurrencyCode = homeCurrencyCode,
)

internal fun CategoryRuleDefinition.toDto(): CategoryRuleRequest = CategoryRuleRequest(
    keyword = keyword,
    category = category,
    enabled = enabled,
    priority = priority,
    amountMinCents = amountMinCents,
    amountMaxCents = amountMaxCents,
    sourceContains = sourceContains,
    tagContains = tagContains,
    homeCurrencyCode = homeCurrencyCode,
)
