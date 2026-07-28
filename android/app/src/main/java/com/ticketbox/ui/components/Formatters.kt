package com.ticketbox.ui.components

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.recordCurrencyDisplay
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
    // 未知码原样亮码（PR#255 R7-2 / R8-4）：原 minor 整数 + 原始码（"1200 VND"）——
    // 未知 exponent 的任何缩放都是猜（不得按 CNY 两位渲染成 "VND12.00"），不冒符号不缩放。
    display.unknownCode?.let { code -> return "$amountCents $code" }
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
            // 零小数币种（JPY/KRW）：任何小数部分都拒绝，不再 HALF_UP 静默进位。
            // 注意这**严于后端 422**：后端按 Decimal 值比较，接受 "1200.0"/"0.00"
            // 这类等值尾零小数，客户端连它们也拒 —— 方向安全（拒而不腐：绝不把
            // 用户没输的尾零静默舍掉）。输入框已由 sanitizeMinorAmountInput 兜底
            // （根本输不进 '.'），本守卫仅直调路径可达。
            if (decimal.scale() > 0) return null
            decimal
        } else {
            decimal.multiply(BigDecimal(100)).setScale(0, RoundingMode.HALF_UP)
        }
        if (scaled < BigDecimal.ZERO) return null
        scaled.longValueExact()
    }.getOrNull()
}

fun formatExpensePrimaryAmount(
    expense: Expense,
    display: CurrencyDisplay = expense.recordCurrencyDisplay(),
): String {
    // R14-3：display 默认 record 口径（原始 home 码，未知码原样亮码），调用方不再透传
    // 恒 Base 的环境 display。原币腿同样 raw 感知：原码未知时按 "1200 VND" 原样亮码，
    // 不冒回落枚举（CNY）的符号与缩放；两腿 display 相等（含同未知码）时才显 home 腿。
    val originalDisplay = CurrencyDisplay.forRecord(
        expense.originalCurrencyCodeRaw ?: expense.originalCurrencyCode.storageKey,
    )
    val originalAmount = expense.originalAmountMinor
    return if (originalDisplay == display || originalAmount == null) {
        formatDisplayAmount(expense.homeAmountCents ?: expense.amountCents, display)
    } else {
        formatDisplayAmount(originalAmount, originalDisplay)
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

/**
 * Home 口径输入框渲染：minor → 主单位文本。币种感知委托（[formatMinorAmountInput]），
 * 调用方必须显式给币种 —— 服务端 `homeCurrencyCode` 可得处用之；仅当流上没有任何
 * record 可带币种（新建 Goal / IncomePlan / 首笔欠款）时才落 [FxContract.HomeCurrency]
 * 兜底（AppViewModel 目前恒以 [CurrencyDisplay.Base] 提供 display home，二者一致）。
 */
fun formatAmountInput(amountCents: Long?, currency: CurrencyCode): String =
    formatMinorAmountInput(amountCents, currency)

/**
 * Home 口径输入框解析：主单位文本 → minor。币种感知委托（[parseMinorAmount]）：
 * 2 位小数币种 ×100（HALF_UP），零小数币种不扩位且拒绝小数部分；负数一律 null。
 * 传参约定同 [formatAmountInput]。
 */
fun parseAmountCents(input: String, currency: CurrencyCode): Long? =
    parseMinorAmount(input, currency)

/**
 * Display 口径的草稿金额解析（PR#255 R15b-2，编辑器 footer/均分用）：已知码同
 * [parseAmountCents]；未知码按原 minor 整数（JPY 零小数代理：不缩放、拒小数）——
 * 与 R8-4 显示（"1200 VND"）/ R10⑥ 搜索代理 / R14-1 回填同一诚实算术空间，不再按
 * 兜底枚举（CNY）把 footer 合计放大 100×。保存侧 `editParseCurrency` 门已 fail-closed，
 * 本函数只决定显示值。
 */
fun parseAmountCentsForDisplay(input: String, display: CurrencyDisplay): Long? =
    parseMinorAmount(
        input,
        if (display.unknownCode != null) CurrencyCode.JPY else display.homeCurrency,
    )

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
