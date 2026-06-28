package com.ticketbox.ui.mascot

import androidx.compose.ui.graphics.Color
import com.ticketbox.ui.design.StateTokens
import com.ticketbox.ui.design.ThemeVisuals

/**
 * 夹夹各部件的主题化配色——MASCOT_BRIEF.md §7.1 映射表的代码单源。
 *
 * 原生 Compose 渲染([MascotPlaceholder])从这里取色,三主题(paper/mono/midnight)
 * 自动换色。若未来再引入外部动画运行时,也必须消费这套语义槽位,禁止另起映射。
 */
data class MascotPalette(
    val bodyFill: Color,
    val bodyHighlight: Color,
    val outline: Color,
    val wireStroke: Color,
    val receiptFill: Color,
    val receiptRule: Color,
    val blushFill: Color,
    val clipAccent: Color,
    val propInfo: Color,
    val propSuccess: Color,
    val propWarn: Color,
)

/** brief §7.1 的逐行映射;改动必须与 brief 表格、web `mascot.*` 绑定三处同步。 */
fun mascotPalette(visuals: ThemeVisuals, states: StateTokens): MascotPalette = MascotPalette(
    bodyFill = visuals.warmMist,
    bodyHighlight = visuals.solidCard,
    outline = visuals.textDefault,
    wireStroke = visuals.textMuted,
    receiptFill = visuals.solidCard,
    receiptRule = visuals.textFaint,
    blushFill = states.danger.border,
    clipAccent = states.danger.fg,
    propInfo = states.info.fg,
    propSuccess = states.success.fg,
    propWarn = states.warn.fg,
)
