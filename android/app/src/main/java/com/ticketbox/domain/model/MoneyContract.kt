package com.ticketbox.domain.model

import java.math.BigDecimal
import java.math.RoundingMode

/** ADR-0073 C07 upper bound for one authoritative money fact in minor units. */
const val MONEY_MINOR_MAX: Long = 9_000_000_000_000L

/** Same canonical major-unit carrier ceiling as the backend wire contract. */
const val MONEY_MAJOR_TEXT_MAX_LENGTH: Int = 64

private val PERCENT_MULTIPLIER = BigDecimal.valueOf(100L)

private val CANONICAL_NONNEGATIVE_MAJOR_PATTERN =
    Regex("^(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$")
private val CANONICAL_SIGNED_MAJOR_PATTERN =
    Regex("^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$")

/** Parse canonical major-unit text only when it maps exactly into the C07 minor envelope. */
fun parseExactMoneyMinor(
    input: String,
    currency: CurrencyCode,
    allowNegative: Boolean = false,
): Long? {
    val value = input.trim()
    val pattern = if (allowNegative) {
        CANONICAL_SIGNED_MAJOR_PATTERN
    } else {
        CANONICAL_NONNEGATIVE_MAJOR_PATTERN
    }
    if (
        value.length > MONEY_MAJOR_TEXT_MAX_LENGTH ||
        !pattern.matches(value) ||
        (value.startsWith('-') && BigDecimal(value).signum() == 0)
    ) {
        return null
    }
    return runCatching {
        val minor = BigDecimal(value)
            .movePointRight(currency.minorUnitDigits)
            .longValueExact()
        val minimum = if (allowNegative) -MONEY_MINOR_MAX else 0L
        minor.takeIf { it in minimum..MONEY_MINOR_MAX }
    }.getOrNull()
}

/** Longest unsigned canonical major-unit form needed to enter [MONEY_MINOR_MAX]. */
fun maxMoneyMajorInputLength(currency: CurrencyCode): Int =
    BigDecimal(MONEY_MINOR_MAX)
        .movePointLeft(currency.minorUnitDigits)
        .toPlainString()
        .length

/**
 * Return a whole percentage without narrowing an aggregate money ratio to [Int]
 * or passing it through binary floating point. Ties use the conventional
 * half-up rule, and a non-positive denominator has no percentage authority.
 */
fun moneyPercent(
    numeratorAmountMinor: Long,
    denominatorAmountMinor: Long,
    absoluteNumerator: Boolean = false,
): Long? {
    if (denominatorAmountMinor <= 0L) return null
    val numerator = BigDecimal.valueOf(numeratorAmountMinor).let { value ->
        if (absoluteNumerator) value.abs() else value
    }
    return numerator
        .multiply(PERCENT_MULTIPLIER)
        .divide(BigDecimal.valueOf(denominatorAmountMinor), 0, RoundingMode.HALF_UP)
        .longValueExact()
}
