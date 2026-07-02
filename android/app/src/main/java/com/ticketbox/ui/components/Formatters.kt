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
fun formatAmount(amountCents: Long?, currency: CurrencyCode = CurrencyCode.Default): String {
    if (amountCents == null) return "待填写金额"
    val locale = Locale.forLanguageTag(currency.localeTag)
    val symbols = DecimalFormatSymbols.getInstance(locale)
    return if (currency.noFractionDigits) {
        // JPY/KRW 等无小数币种：minor 已等于 major，不再除以 100
        val pattern = DecimalFormat("#,##0", symbols)
        "${currency.symbol}${pattern.format(amountCents)}"
    } else {
        val yuan = BigDecimal(amountCents).divide(BigDecimal(100), 2, RoundingMode.HALF_UP)
        val pattern = DecimalFormat("#,##0.00", symbols)
        "${currency.symbol}${pattern.format(yuan)}"
    }
}

fun formatDisplayAmount(amountCents: Long?, display: CurrencyDisplay = CurrencyDisplay.Base): String {
    if (amountCents == null) return "待填写金额"
    return formatAmount(amountCents, display.homeCurrency)
}

fun formatMinorAmount(amountMinor: Long?, currency: CurrencyCode): String {
    if (amountMinor == null) return "待填写金额"
    val locale = Locale.forLanguageTag(currency.localeTag)
    val symbols = DecimalFormatSymbols.getInstance(locale)
    return if (currency.noFractionDigits) {
        val pattern = DecimalFormat("#,##0", symbols)
        "${currency.symbol}${pattern.format(amountMinor)}"
    } else {
        val major = BigDecimal(amountMinor).divide(BigDecimal(100), 2, RoundingMode.HALF_UP)
        val pattern = DecimalFormat("#,##0.00", symbols)
        "${currency.symbol}${pattern.format(major)}"
    }
}

fun formatMinorAmountInput(amountMinor: Long?, currency: CurrencyCode): String {
    if (amountMinor == null) return ""
    return if (currency.noFractionDigits) {
        amountMinor.toString()
    } else {
        BigDecimal(amountMinor).divide(BigDecimal(100), 2, RoundingMode.HALF_UP).toPlainString()
    }
}

fun sanitizeMinorAmountInput(input: String, currency: CurrencyCode, maxLength: Int = 12): String {
    val trimmed = input.trim()
    if (currency.noFractionDigits) {
        return trimmed
            .takeWhile { it != '.' }
            .filter(Char::isDigit)
            .take(maxLength)
    }
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

fun parseMinorAmount(input: String, currency: CurrencyCode): Long? {
    val trimmed = input.trim()
    if (trimmed.isBlank()) return null
    return runCatching {
        val decimal = BigDecimal(trimmed)
        val scaled = if (currency.noFractionDigits) {
            decimal.setScale(0, RoundingMode.HALF_UP)
        } else {
            decimal.multiply(BigDecimal(100)).setScale(0, RoundingMode.HALF_UP)
        }
        if (scaled < BigDecimal.ZERO) return null
        scaled.longValueExact()
    }.getOrNull()
}

fun formatExpensePrimaryAmount(
    expense: Expense,
    display: CurrencyDisplay = CurrencyDisplay.Base,
): String {
    val currency = expense.originalCurrencyCode
    val homeCurrency = expense.homeCurrency
    val originalAmount = expense.originalAmountMinor
    return if (currency == homeCurrency || originalAmount == null) {
        formatDisplayAmount(expense.homeAmountCents ?: expense.amountCents, display)
    } else {
        formatMinorAmount(originalAmount, currency)
    }
}

fun formatExpenseExchangeMeta(expense: Expense): String? {
    val currency = expense.originalCurrencyCode
    if (currency == expense.homeCurrency) return null
    val date = (expense.fxRateDate ?: expense.exchangeRateDate)?.takeIf { it.isNotBlank() }
    if (expense.fxStatus == FxContract.StatusPending || expense.fxRate.isNullOrBlank() || expense.homeAmountCents == null) {
        return buildString {
            append("汇率待同步")
            if (date != null) append(" · ").append(date)
        }
    }
    val rate = expense.fxRate.trim()
    val cny = formatAmount(expense.homeAmountCents, expense.homeCurrency)
    return buildString {
        append("≈ ").append(cny)
        append(" · 汇率 1 ").append(currency.storageKey).append(" = ").append(rate).append(" ")
        append(expense.homeCurrency.storageKey)
        if (date != null) append(" · ").append(date)
    }
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
