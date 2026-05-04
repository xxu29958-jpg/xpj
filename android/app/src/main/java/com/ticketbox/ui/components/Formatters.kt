package com.ticketbox.ui.components

import java.math.BigDecimal
import java.math.RoundingMode
import java.text.NumberFormat
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

fun formatAmount(amountCents: Long?): String {
    if (amountCents == null) return "待填写金额"
    val yuan = BigDecimal(amountCents).divide(BigDecimal(100), 2, RoundingMode.HALF_UP)
    return NumberFormat.getCurrencyInstance(Locale.CHINA).format(yuan)
}

fun formatAmountInput(amountCents: Long?): String {
    if (amountCents == null) return ""
    return BigDecimal(amountCents).divide(BigDecimal(100), 2, RoundingMode.HALF_UP).toPlainString()
}

fun parseAmountCents(input: String): Long? {
    val trimmed = input.trim()
    if (trimmed.isBlank()) return null
    return runCatching {
        BigDecimal(trimmed)
            .multiply(BigDecimal(100))
            .setScale(0, RoundingMode.HALF_UP)
            .longValueExact()
    }.getOrNull()
}

fun displayTime(value: String?): String {
    if (value.isNullOrBlank()) return "未填写时间"
    val localZone = ZoneId.systemDefault()
    val formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm").withZone(localZone)
    return runCatching { formatter.format(Instant.parse(value)) }
        .recoverCatching { formatter.format(OffsetDateTime.parse(value).toInstant()) }
        .getOrElse { value.replace("T", " ").removeSuffix("Z") }
}

fun formatStorageSize(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val kb = BigDecimal(bytes).divide(BigDecimal(1024), 1, RoundingMode.HALF_UP)
    if (kb < BigDecimal(1024)) return "${kb.stripTrailingZeros().toPlainString()} KB"
    val mb = kb.divide(BigDecimal(1024), 1, RoundingMode.HALF_UP)
    if (mb < BigDecimal(1024)) return "${mb.stripTrailingZeros().toPlainString()} MB"
    val gb = mb.divide(BigDecimal(1024), 1, RoundingMode.HALF_UP)
    return "${gb.stripTrailingZeros().toPlainString()} GB"
}
