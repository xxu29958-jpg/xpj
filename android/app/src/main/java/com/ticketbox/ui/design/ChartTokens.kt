package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class ChartTokens(
    val series: List<Color>,
    val sequentialFrom: Color,
    val sequentialTo: Color,
    val divergingNegative: Color,
    val divergingZero: Color,
    val divergingPositive: Color,
    val axis: Color,
    val axisLabel: Color,
    val grid: Color,
    val gridEmphasis: Color,
    val tooltipBg: Color,
    val tooltipFg: Color,
    val tooltipBorder: Color,
    val legendFg: Color,
    val legendMarker: Color,
    val sankeyRibbon: Color,
    val sankeyRibbonEmphasis: Color,
    val overspend: Color,
    val empty: Color,
)

val LocalChartTokens = compositionLocalOf { chartTokensForSkin(AppSkin.Default) }

fun chartTokensForSkin(skin: AppSkin): ChartTokens {
    return when (skin) {
        AppSkin.Paper -> ChartTokens(
            series = listOf(
                Color(0xFF8A5A2B),
                Color(0xFF1C1A18),
                Color(0xFF4F6B3A),
                Color(0xFFA4361C),
                Color(0xFF3E6770),
                Color(0xFFD6B487),
                Color(0xFF5A4A6E),
                Color(0xFF807968),
            ),
            sequentialFrom = Color(0xFFF1E7D5),
            sequentialTo = Color(0xFF6F4621),
            divergingNegative = Color(0xFFA4361C),
            divergingZero = Color(0xFFECE7D8),
            divergingPositive = Color(0xFF4F6B3A),
            axis = Color(0xFFAAA294),
            axisLabel = Color(0xFF4A463F),
            grid = Color(0x141C1A18),
            gridEmphasis = Color(0x668A5A2B),
            tooltipBg = Color(0xFF1C1A18),
            tooltipFg = Color(0xFFFBF8F1),
            tooltipBorder = Color(0xFF3A3530),
            legendFg = Color(0xFF1C1A18),
            legendMarker = Color(0xFFFBF8F1),
            sankeyRibbon = Color(0x4D8A5A2B),
            sankeyRibbonEmphasis = Color(0xCC6F4621),
            overspend = Color(0xFFA4361C),
            empty = Color(0xFFDDD6C5),
        )
        AppSkin.Mono -> ChartTokens(
            series = listOf(
                Color(0xFF0E0E0C),
                Color(0xFF6F6E6A),
                Color(0xFF2C5036),
                Color(0xFF8E1D12),
                Color(0xFF3A4A52),
                Color(0xFF665015),
                Color(0xFF5A4A6E),
                Color(0xFFADACA7),
            ),
            sequentialFrom = Color(0xFFE8E7E3),
            sequentialTo = Color(0xFF0E0E0C),
            divergingNegative = Color(0xFF8E1D12),
            divergingZero = Color(0xFFE3E2DD),
            divergingPositive = Color(0xFF2C5036),
            axis = Color(0xFFA6A5A0),
            axisLabel = Color(0xFF3A3A37),
            grid = Color(0x0F000000),
            gridEmphasis = Color(0x660E0E0C),
            tooltipBg = Color(0xFF0E0E0C),
            tooltipFg = Color(0xFFFAFAF8),
            tooltipBorder = Color(0xFF2A2A28),
            legendFg = Color(0xFF0E0E0C),
            legendMarker = Color(0xFFFAFAF8),
            sankeyRibbon = Color(0x330E0E0C),
            sankeyRibbonEmphasis = Color(0xB30E0E0C),
            overspend = Color(0xFF8E1D12),
            empty = Color(0xFFD6D5D0),
        )
        AppSkin.Midnight -> ChartTokens(
            // series 5-8 跨色相重排（plum / teal 族），脱离 1-4 暖金/鼠尾草/陶土/天蓝 邻位；
            // 逐色对 #15171c 卡底 WCAG 对比度：5=7.95 6=7.05 7=6.42 8=7.75（均 ≥3:1）。
            // 与 shared/tokens.css [data-theme=midnight] 的 --chart-series-5..8 逐值镜像。
            series = listOf(
                Color(0xFFD6B487),
                Color(0xFFA8B88A),
                Color(0xFFD97757),
                Color(0xFF84BCD4),
                Color(0xFFC9A0C4),
                Color(0xFF5FB0A8),
                Color(0xFFB88AC9),
                Color(0xFF6CBA93),
            ),
            sequentialFrom = Color(0xFF1C1F25),
            sequentialTo = Color(0xFFD6B487),
            divergingNegative = Color(0xFFD97757),
            divergingZero = Color(0xFF2A2D35),
            divergingPositive = Color(0xFFA8B88A),
            axis = Color(0xFF5E636F),
            axisLabel = Color(0xFFB8B4A8),
            grid = Color(0x0FFFFFFF),
            gridEmphasis = Color(0x66D6B487),
            tooltipBg = Color(0xFF08090C),
            tooltipFg = Color(0xFFE9E7DF),
            tooltipBorder = Color(0xFF2A2D35),
            legendFg = Color(0xFFE9E7DF),
            legendMarker = Color(0xFF15171C),
            sankeyRibbon = Color(0x33D6B487),
            sankeyRibbonEmphasis = Color(0xB3D6B487),
            overspend = Color(0xFFD97757),
            empty = Color(0xFF2A2D35),
        )
    }
}
