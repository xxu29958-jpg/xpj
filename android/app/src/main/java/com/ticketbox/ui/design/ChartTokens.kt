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
                Color(0xFF14504A),
                Color(0xFF26322D),
                Color(0xFFA9783E),
                Color(0xFFB65E47),
                Color(0xFF55747A),
                Color(0xFF7F8F68),
                Color(0xFF756A8A),
                Color(0xFF8C9691),
            ),
            sequentialFrom = Color(0xFFE2ECDF),
            sequentialTo = Color(0xFF0D3D38),
            divergingNegative = Color(0xFFB65E47),
            divergingZero = Color(0xFFE7ECE8),
            divergingPositive = Color(0xFF14504A),
            axis = Color(0xFFAAA596),
            axisLabel = Color(0xFF57514A),
            grid = Color(0x141D1A15),
            gridEmphasis = Color(0x6614504A),
            tooltipBg = Color(0xFF1D1A15),
            tooltipFg = Color(0xFFF7F5EF),
            tooltipBorder = Color(0xFF3A352A),
            legendFg = Color(0xFF1D1A15),
            legendMarker = Color(0xFFF7F5EF),
            sankeyRibbon = Color(0x4D14504A),
            sankeyRibbonEmphasis = Color(0xCC0D3D38),
            overspend = Color(0xFFB65E47),
            empty = Color(0xFFDDD7C8),
        )
        AppSkin.Midnight -> ChartTokens(
            series = listOf(
                Color(0xFF70BFA5),
                Color(0xFFB7C4BD),
                Color(0xFFE3B36C),
                Color(0xFFE0836F),
                Color(0xFF8DB8C0),
                Color(0xFFA7B98C),
                Color(0xFFB19DB8),
                Color(0xFF7F9188),
            ),
            sequentialFrom = Color(0xFF1C2320),
            sequentialTo = Color(0xFF70BFA5),
            divergingNegative = Color(0xFFE0836F),
            divergingZero = Color(0xFF303A35),
            divergingPositive = Color(0xFF70BFA5),
            axis = Color(0xFF4D5A54),
            axisLabel = Color(0xFFAAB5AF),
            grid = Color(0x0FFFFFFF),
            gridEmphasis = Color(0x6670BFA5),
            tooltipBg = Color(0xFF0D110F),
            tooltipFg = Color(0xFFE8EEEA),
            tooltipBorder = Color(0xFF303A35),
            legendFg = Color(0xFFE8EEEA),
            legendMarker = Color(0xFF151A17),
            sankeyRibbon = Color(0x3370BFA5),
            sankeyRibbonEmphasis = Color(0xB370BFA5),
            overspend = Color(0xFFE0836F),
            empty = Color(0xFF303A35),
        )
    }
}
