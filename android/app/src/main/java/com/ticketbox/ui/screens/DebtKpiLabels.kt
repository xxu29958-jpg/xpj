package com.ticketbox.ui.screens

/**
 * ADR-0049 §7.0 / 8e-6b 外部债 KPI 的纯 label helpers（独立成文件——DebtGoalLabels 已接近文件级
 * TooManyFunctions 门，[[project_android_compose_detekt_limits]]）。
 *
 * 投影还清日期来自服务端 ISO 日期串（`projected_payoff_date`），UI 按**月粒度**呈现：velocity 投影本身
 * 有不确定性，精确到「日」是假精度；用户要的也是「大概 X 个月还完」，月粒度 + 「前后」更诚实（§7.0 R4）。
 */

/**
 * 把 ISO 日期串（`"2026-09-01"`）解析成 `(year, month)`；不可解析 / 非法月返回 `null`（投影串容错——
 * 调用方据此降级到「数据不足」文案，绝不渲染假日期）。只取年月，刻意丢弃「日」。
 */
internal fun parsePayoffYearMonth(isoDate: String): Pair<Int, Int>? {
    val parts = isoDate.split("-")
    if (parts.size < 2) return null
    val year = parts[0].toIntOrNull() ?: return null
    val month = parts[1].toIntOrNull() ?: return null
    return if (month in 1..12) year to month else null
}
