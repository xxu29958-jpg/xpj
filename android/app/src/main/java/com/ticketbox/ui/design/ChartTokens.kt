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
        AppSkin.Mono -> ChartTokens(
            series = listOf(
                Color(0xFF202824),
                Color(0xFF6A746F),
                Color(0xFF315A45),
                Color(0xFF8C3B32),
                Color(0xFF485A5F),
                Color(0xFF79653B),
                Color(0xFF655F72),
                Color(0xFFAAB3AE),
            ),
            sequentialFrom = Color(0xFFE5EAE7),
            sequentialTo = Color(0xFF202824),
            divergingNegative = Color(0xFF8C3B32),
            divergingZero = Color(0xFFE8ECE9),
            divergingPositive = Color(0xFF315A45),
            axis = Color(0xFFA9B0AC),
            axisLabel = Color(0xFF626965),
            grid = Color(0x0F000000),
            gridEmphasis = Color(0x66202824),
            tooltipBg = Color(0xFF171B19),
            tooltipFg = Color(0xFFF7F8F7),
            tooltipBorder = Color(0xFF353D39),
            legendFg = Color(0xFF171B19),
            legendMarker = Color(0xFFF7F8F7),
            sankeyRibbon = Color(0x33202824),
            sankeyRibbonEmphasis = Color(0xB3202824),
            overspend = Color(0xFF8C3B32),
            empty = Color(0xFFD8DEDA),
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
