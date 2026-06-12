package com.ticketbox.ui.mascot

import androidx.compose.ui.graphics.Color
import com.ticketbox.ui.design.StateTokens
import com.ticketbox.ui.design.ThemeVisuals

/**
 * 夹夹各部件的主题化配色——MASCOT_BRIEF.md §7.1 映射表的代码单源。
 *
 * 占位渲染([MascotPlaceholder])和未来的 Rive 运行时绑色(ADR-0048,把这些值
 * 喂给 .riv 的 `mascot.*` 语义色)都从这里取,三主题(paper/mono/midnight)
 * 自动换色,禁止任何一端另起映射。
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
    bodyFill = visuals.surfaceSunken,
    bodyHighlight = visuals.solidCard,
    outline = visuals.textDefault,
    wireStroke = visuals.textMuted,
    receiptFill = visuals.solidCard,
    receiptRule = visuals.textFaint,
    blushFill = states.danger.bg,
    clipAccent = visuals.primary,
    propInfo = states.info.fg,
    propSuccess = states.success.fg,
    propWarn = states.warn.fg,
)
