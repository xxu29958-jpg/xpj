package com.ticketbox.presentation

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.maxMoneyMajorInputLength
import com.ticketbox.domain.model.parseExactMoneyMinor
import java.math.BigDecimal

fun formatMinorAmountInput(amountMinor: Long?, currency: CurrencyCode): String =
    amountMinor?.let { BigDecimal.valueOf(it, currency.minorUnitDigits).toPlainString() }.orEmpty()

fun sanitizeMinorAmountInput(
    input: String,
    currency: CurrencyCode,
    maxLength: Int = maxMoneyMajorInputLength(currency),
): String {
    val trimmed = input.trim()
    val lengthLimit = maxLength.coerceAtLeast(0)
    if (lengthLimit == 0) return ""
    if (currency.noFractionDigits) {
        return trimmed
            .takeWhile { it != '.' }
            .filter(Char::isDigit)
            .take(lengthLimit)
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
        if (builder.length >= lengthLimit) break
    }
    return builder.toString()
}

fun parseMinorAmount(input: String, currency: CurrencyCode): Long? =
    parseExactMoneyMinor(input, currency)

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
 * 按币种 exponent 精确移位；无法精确落到整数 minor、越过 C07 上界或负数一律 null。
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

