package com.ticketbox.domain.model

import java.math.BigDecimal

private const val MAX_MANUAL_EXCHANGE_RATE_LENGTH = 64
private const val MAX_MANUAL_EXCHANGE_RATE_SCALE = 8
private val MAX_MANUAL_EXCHANGE_RATE = BigDecimal("9999999999.99999999")
private val CANONICAL_POSITIVE_EXCHANGE_RATE = Regex("^(?:[1-9][0-9]*(?:\\.[0-9]+)?|0\\.[0-9]*[1-9][0-9]*)$")

internal fun sanitizeManualExchangeRateInput(raw: String): String = raw.take(MAX_MANUAL_EXCHANGE_RATE_LENGTH)

internal fun canonicalManualExchangeRateOrNull(raw: String): String? {
    val canonical = raw.trim()
    if (canonical.length > MAX_MANUAL_EXCHANGE_RATE_LENGTH || !CANONICAL_POSITIVE_EXCHANGE_RATE.matches(canonical)) return null
    val decimal = canonical.toBigDecimalOrNull() ?: return null
    if (decimal.stripTrailingZeros().scale() > MAX_MANUAL_EXCHANGE_RATE_SCALE || decimal > MAX_MANUAL_EXCHANGE_RATE) return null
    return canonical
}
