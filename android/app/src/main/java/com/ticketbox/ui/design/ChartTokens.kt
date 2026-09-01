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
                Color(0xFF176B5B),
                Color(0xFF26322D),
                Color(0xFFA9783E),
                Color(0xFFB65E47),
                Color(0xFF55747A),
                Color(0xFF7F8F68),
                Color(0xFF756A8A),
                Color(0xFF8C9691),
            ),
            sequentialFrom = Color(0xFFE1F0EA),
            sequentialTo = Color(0xFF0E5146),
            divergingNegative = Color(0xFFB65E47),
            divergingZero = Color(0xFFE7ECE8),
            divergingPositive = Color(0xFF176B5B),
            axis = Color(0xFFAAB4AE),
            axisLabel = Color(0xFF66716B),
            grid = Color(0x1417201C),
            gridEmphasis = Color(0x66176B5B),
            tooltipBg = Color(0xFF17201C),
            tooltipFg = Color(0xFFF7F8F6),
            tooltipBorder = Color(0xFF34413B),
            legendFg = Color(0xFF17201C),
            legendMarker = Color(0xFFF7F8F6),
            sankeyRibbon = Color(0x4D176B5B),
            sankeyRibbonEmphasis = Color(0xCC0E5146),
            overspend = Color(0xFFB65E47),
            empty = Color(0xFFDCE2DD),
        )
        AppSkin.Midnight -> ChartTokens(
            series = listOf(
                Color(0xFF69BFA4),
                Color(0xFFB7C4BD),
                Color(0xFFE3B36C),
                Color(0xFFE0836F),
                Color(0xFF8DB8C0),
                Color(0xFFA7B98C),
                Color(0xFFB19DB8),
                Color(0xFF7F9188),
            ),
            sequentialFrom = Color(0xFF1C2320),
            sequentialTo = Color(0xFF69BFA4),
            divergingNegative = Color(0xFFE0836F),
            divergingZero = Color(0xFF303A35),
            divergingPositive = Color(0xFF69BFA4),
            axis = Color(0xFF4D5A54),
            axisLabel = Color(0xFFAAB5AF),
            grid = Color(0x0FFFFFFF),
            gridEmphasis = Color(0x6669BFA4),
            tooltipBg = Color(0xFF0D110F),
            tooltipFg = Color(0xFFE8EEEA),
            tooltipBorder = Color(0xFF303A35),
            legendFg = Color(0xFFE8EEEA),
            legendMarker = Color(0xFF151A17),
            sankeyRibbon = Color(0x3369BFA4),
            sankeyRibbonEmphasis = Color(0xB369BFA4),
            overspend = Color(0xFFE0836F),
            empty = Color(0xFF303A35),
        )
    }
}
