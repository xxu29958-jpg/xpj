package com.ticketbox.ui.components

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FxContract
import java.math.BigDecimal
import java.math.RoundingMode
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Locale

/**
 * 把传入金额格式化为带币种符号的字符串。
 *
 * 契约：[amountCents] 是 [currency] 自己的 minor-unit 数值。
 * - CNY/USD/EUR... 等 2 位小数币种：除以 100 显示主单位
 * - JPY/KRW 等无小数币种：minor unit == major unit，直接整数显示
 *
 * 本函数不做汇率折算。展示后端 home amount 时使用 [formatDisplayAmount]，
 * 它会传入 backend home currency 让 minor-unit 语义一致。
 */
fun formatAmount(amountCents: Long?, currency: CurrencyCode): String {
    return formatMinorAmount(amountCents, currency)
}

fun formatDisplayAmount(amountCents: Long?, display: CurrencyDisplay): String {
    if (amountCents == null) return "待填写金额"
    return formatAmount(amountCents, display.homeCurrency)
}

fun formatMinorAmount(amountMinor: Long?, currency: CurrencyCode): String {
    if (amountMinor == null) return "待填写金额"
    val locale = Locale.forLanguageTag(currency.localeTag)
    val symbols = DecimalFormatSymbols.getInstance(locale)
    val patternText = if (currency.noFractionDigits) "#,##0" else "#,##0.${"0".repeat(currency.minorUnitDigits)}"
    val pattern = DecimalFormat(patternText, symbols)
    val major = BigDecimal.valueOf(amountMinor).movePointLeft(currency.minorUnitDigits)
    val sign = if (amountMinor < 0L) "-" else ""
    return "$sign${currency.symbol}${pattern.format(major.abs())}"
}

fun formatMinorAmountInput(amountMinor: Long?, currency: CurrencyCode): String {
    if (amountMinor == null) return ""
    return BigDecimal.valueOf(amountMinor)
        .movePointLeft(currency.minorUnitDigits)
        .setScale(currency.minorUnitDigits)
        .toPlainString()
}

fun sanitizeMinorAmountInput(input: String, maxLength: Int = 12): String {
    val trimmed = input.trim()
    val builder = StringBuilder()
    var hasDecimal = false
    for (char in trimmed) {
        when {
            char.isDigit() -> builder.append(char)
            char == '.' && !hasDecimal -> {
                builder.append(char)
                hasDecimal = true
            }
        }
        if (builder.length >= maxLength) break
    }
    return builder.toString()
}

fun parseMinorAmount(
    input: String,
    currency: CurrencyCode,
    allowNegative: Boolean = false,
): Long? {
    val trimmed = input.trim()
    if (trimmed.isBlank()) return null
    return runCatching {
        val decimal = BigDecimal(trimmed)
        if (!allowNegative && decimal.signum() < 0) return null
        decimal
            .setScale(currency.minorUnitDigits, RoundingMode.UNNECESSARY)
            .movePointRight(currency.minorUnitDigits)
            .longValueExact()
    }.getOrNull()
}

fun formatExpensePrimaryAmount(
    expense: Expense,
): String {
    val currency = expense.originalCurrencyCode
    val homeCurrency = expense.homeCurrency
    val originalAmount = expense.originalAmountMinor
    return if (currency == homeCurrency || originalAmount == null) {
        formatAmount(expense.homeAmountCents ?: expense.amountCents, homeCurrency)
    } else {
        "${formatMinorAmount(originalAmount, currency)} ${currency.storageKey}"
    }
}

fun formatExpenseExchangeMeta(
    expense: Expense,
    pendingRateLabel: String,
): String? {
    val currency = expense.originalCurrencyCode
    if (currency == expense.homeCurrency) return null
    val date = (expense.fxRateDate ?: expense.exchangeRateDate)?.takeIf { it.isNotBlank() }
    if (expense.fxStatus == FxContract.StatusPending || expense.fxRate.isNullOrBlank() || expense.homeAmountCents == null) {
        return buildString {
            append(currency.storageKey)
                .append(" → ")
                .append(expense.homeCurrency.storageKey)
                .append(" · ")
                .append(pendingRateLabel)
            if (date != null) append(" · ").append(date)
        }
    }
    val rate = expense.fxRate.trim()
    val homeAmount = formatAmount(expense.homeAmountCents, expense.homeCurrency)
    return buildString {
        append("≈ ").append(homeAmount)
        append(" · 汇率 1 ").append(currency.storageKey).append(" = ").append(rate).append(" ")
        append(expense.homeCurrency.storageKey)
        if (date != null) append(" · ").append(date)
    }
}

fun formatAmountInput(amountMinor: Long?, currency: CurrencyCode): String =
    formatMinorAmountInput(amountMinor, currency)

fun parseAmountCents(
    input: String,
    currency: CurrencyCode,
    allowNegative: Boolean = false,
): Long? = parseMinorAmount(input, currency, allowNegative)

fun displayTime(value: String?): String {
    if (value.isNullOrBlank()) return "未填写时间"
    val localZone = ZoneId.systemDefault()
    val formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm").withZone(localZone)
    return runCatching { formatter.format(Instant.parse(value)) }
        .recoverCatching { formatter.format(OffsetDateTime.parse(value).toInstant()) }
        .getOrElse { value.replace("T", " ").removeSuffix("Z") }
}

fun displayCompactTime(value: String?): String {
    val localDateTime = parseLocalDateTime(value) ?: return displayTime(value)
    return localDateTime.format(DateTimeFormatter.ofPattern("M/d HH:mm"))
}

fun displayDate(value: String?): String {
    if (value.isNullOrBlank()) return "未设置"
    val localZone = ZoneId.systemDefault()
    val formatter = DateTimeFormatter.ofPattern("yyyy年M月d日").withZone(localZone)
    return runCatching { formatter.format(Instant.parse(value)) }
        .recoverCatching { formatter.format(OffsetDateTime.parse(value).toInstant()) }
        .getOrElse { value.take(10) }
}

fun displayDateTime(value: String?): String {
    if (value.isNullOrBlank()) return "未设置"
    val formatter = DateTimeFormatter.ofPattern("yyyy年M月d日 HH:mm")
    return parseLocalDateTime(value)
        ?.format(formatter)
        ?: value.replace("T", " ").removeSuffix("Z")
}

fun selectedDateMillisFromIso(value: String?, zoneId: ZoneId = ZoneId.systemDefault()): Long? {
    if (value.isNullOrBlank()) return null
    val localDate = parseLocalDateTime(value, zoneId)
        ?.toLocalDate()
        ?: return null
    return localDate.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
}

fun selectedHourFromIso(value: String?, zoneId: ZoneId = ZoneId.systemDefault()): Int {
    return parseLocalDateTime(value, zoneId)?.hour ?: LocalTime.now(zoneId).hour
}

fun selectedMinuteFromIso(value: String?, zoneId: ZoneId = ZoneId.systemDefault()): Int {
    return parseLocalDateTime(value, zoneId)?.minute ?: LocalTime.now(zoneId).minute
}

fun datePickerMillisToUtcIso(
    value: Long,
    currentIso: String? = null,
    zoneId: ZoneId = ZoneId.systemDefault(),
): String {
    val selectedDate = Instant.ofEpochMilli(value).atZone(ZoneOffset.UTC).toLocalDate()
    val time = parseLocalDateTime(currentIso, zoneId)?.toLocalTime()
        ?: LocalTime.now(zoneId).truncatedTo(ChronoUnit.MINUTES)
    return LocalDateTime.of(selectedDate, time)
        .atZone(zoneId)
        .toInstant()
        .toString()
}

fun timePickerToUtcIso(
    hour: Int,
    minute: Int,
    currentIso: String? = null,
    zoneId: ZoneId = ZoneId.systemDefault(),
): String {
    val date = parseLocalDateTime(currentIso, zoneId)?.toLocalDate()
        ?: LocalDate.now(zoneId)
    return LocalDateTime.of(date, LocalTime.of(hour, minute))
        .atZone(zoneId)
        .toInstant()
        .toString()
}

fun nowUtcIso(zoneId: ZoneId = ZoneId.systemDefault()): String {
    return LocalDateTime.now(zoneId)
        .truncatedTo(ChronoUnit.MINUTES)
        .atZone(zoneId)
        .toInstant()
        .toString()
}

private fun parseLocalDateTime(
    value: String?,
    zoneId: ZoneId = ZoneId.systemDefault(),
): LocalDateTime? {
    if (value.isNullOrBlank()) return null
    return runCatching { Instant.parse(value).atZone(zoneId).toLocalDateTime() }
        .recoverCatching { OffsetDateTime.parse(value).toInstant().atZone(zoneId).toLocalDateTime() }
        .recoverCatching { LocalDateTime.parse(value) }
        .recoverCatching { LocalDate.parse(value.take(10)).atStartOfDay() }
        .getOrNull()
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
