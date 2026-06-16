package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import com.ticketbox.R
import com.ticketbox.domain.model.DebtThreeStates
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTokens
import com.ticketbox.ui.design.StateTone
import java.time.LocalDate
import java.time.ZoneOffset

/**
 * ADR-0049 §7.0 / 8e-6b+6c 外部债 KPI 的纯 label/tone helpers（独立成文件——DebtGoalLabels 已接近文件级
 * TooManyFunctions 门，[[project_android_compose_detekt_limits]]）。
 *
 * 投影还清日期来自服务端 ISO 日期串（`projected_payoff_date` / `target_date`），UI 按**月粒度**呈现：
 * velocity 投影本身有不确定性，精确到「日」是假精度；用户要的也是「大概 X 个月还完」，月粒度 + 「前后」更
 * 诚实（§7.0 R4）。三态（6c）是**纯外部债**的会计 KPI（§8 允许 businesslike），但 at_risk **绝不 shame**：
 * 事实性「晚于计划」、琥珀/warn 非红、无第二人称指责、无「更快还清」催（§7.0 去-shame）。
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

/**
 * ISO 日期串 → Material3 DatePicker 的 UTC 毫秒（用于回显当前还清日期作选中初值）；不可解析返回 `null`。
 * 全程 UTC（picker 报的是选中日的 UTC 午夜毫秒），与 [com.ticketbox.viewmodel] 的回向转换对称、日不漂移。
 */
internal fun isoDateToEpochMillis(isoDate: String): Long? =
    runCatching { LocalDate.parse(isoDate).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli() }
        .getOrNull()

/**
 * 三态文案（@StringRes，纯函数）：**事实性、去-shame**。at_risk = 「可能晚于计划」（不是「你落后了」、不催）。
 * 未知值降级 on_track（防御性兜底，不崩）；只在 `three_state != null` 时渲染（调用方 gate）。
 */
@StringRes
internal fun debtThreeStateLabelRes(state: String): Int = when (state) {
    DebtThreeStates.ON_TRACK -> R.string.debt_three_state_on_track
    DebtThreeStates.AHEAD -> R.string.debt_three_state_ahead
    DebtThreeStates.AT_RISK -> R.string.debt_three_state_at_risk
    else -> R.string.debt_three_state_on_track
}

/**
 * 三态色调档（纯函数，可单测 §7.0 红线「at_risk 绝不 danger/红」）：枚举**刻意无 Danger 变体**，故 resolver
 * 结构上永不可能返回 danger。ahead→success、on_track→info、at_risk→**warn（琥珀）**。
 */
internal enum class DebtThreeStateTone { OnTrack, Ahead, AtRisk }

internal fun debtThreeStateToneKind(state: String): DebtThreeStateTone = when (state) {
    DebtThreeStates.AHEAD -> DebtThreeStateTone.Ahead
    DebtThreeStates.AT_RISK -> DebtThreeStateTone.AtRisk
    else -> DebtThreeStateTone.OnTrack
}

/**
 * [DebtThreeStateTone] → [StateTone] 的**纯解析**（可 JVM 单测 §7.0 红线「at_risk 绝不 danger/红」——上色的就是这条
 * arm，不是无 Danger 变体的枚举〔那是同义反复〕）：ahead→success、on_track→info、at_risk→**warn（琥珀）**。
 */
internal fun debtThreeStateTone(tone: DebtThreeStateTone, tokens: StateTokens): StateTone = when (tone) {
    DebtThreeStateTone.Ahead -> tokens.success
    DebtThreeStateTone.OnTrack -> tokens.info
    DebtThreeStateTone.AtRisk -> tokens.warn
}

/** [debtThreeStateToneKind] 的 @Composable 色解析（委托纯 [debtThreeStateTone] 重载，读 [LocalStateTokens]）。 */
@Composable
internal fun debtThreeStateTone(state: String): StateTone =
    debtThreeStateTone(debtThreeStateToneKind(state), LocalStateTokens.current)
