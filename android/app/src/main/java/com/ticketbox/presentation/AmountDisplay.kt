package com.ticketbox.presentation

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.recordCurrencyDisplay
import java.math.BigDecimal
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
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
    val digits = currency.minorUnitDigits
    val pattern = DecimalFormat("#,##0" + if (digits == 0) "" else "." + "0".repeat(digits), symbols)
    // The sign reads before the currency (-¥500), as on the web and in the v0.6 designs.
    val sign = if (amountCents < 0) "-" else ""
    return "$sign${currency.symbol}${pattern.format(BigDecimal.valueOf(amountCents, digits).abs())}"
}

fun formatDisplayAmount(amountCents: Long?, display: CurrencyDisplay = CurrencyDisplay.Base): String {
    if (amountCents == null) return "待填写金额"
    // 未知码原样亮码（PR#255 R7-2 / R8-4）：原 minor 整数 + 原始码（"1200 VND"）——
    // 未知 exponent 的任何缩放都是猜（不得按 CNY 两位渲染成 "VND12.00"），不冒符号不缩放。
    display.unknownCode?.let { code -> return "$amountCents $code" }
    return formatAmount(amountCents, display.homeCurrency)
}

fun formatMinorAmount(amountMinor: Long?, currency: CurrencyCode): String = formatAmount(amountMinor, currency)

internal fun CurrencyCode.symbolAndCodeLabel(): String =
    symbol.trim().let { if (it == storageKey) storageKey else "$it $storageKey" }

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

