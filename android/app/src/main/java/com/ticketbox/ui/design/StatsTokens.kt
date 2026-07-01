package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin

data class StatsSurfaceTokens(
    val hero: StatsSurfaceStyleTokens,
    val section: StatsSurfaceStyleTokens,
)

data class StatsSurfaceStyleTokens(
    val radius: Dp,
    val topAlpha: Float,
    val bottomAlpha: Float,
    val borderAlpha: Float,
)

enum class StatsSurfaceTone {
    Hero,
    Section,
}

data class StatsControlTokens(
    val height: Dp,
    val horizontalPadding: Dp,
    val selectedAlpha: Float,
    val unselectedAlpha: Float,
    val borderAlpha: Float,
)

data class StatsChartTokens(
    val overviewHeight: Dp,
    val monthlyHeight: Dp,
    val recentHeight: Dp,
    val distributionHeight: Dp,
    val distribution: StatsDistributionTokens,
    val guideAlpha: Float,
    val quietAlpha: Float,
    val emphasisAlpha: Float,
    val comparison: StatsComparisonChartTokens,
)

data class StatsTokens(
    val surface: StatsSurfaceTokens,
    val control: StatsControlTokens,
    val chart: StatsChartTokens,
)

val LocalStatsTokens = compositionLocalOf { statsTokensForSkin(AppSkin.Default) }

fun statsTokensForSkin(skin: AppSkin): StatsTokens = when (skin) {
    AppSkin.Paper -> paperStatsTokens()
    AppSkin.Mono -> monoStatsTokens()
    AppSkin.Midnight -> midnightStatsTokens()
}

data class StatsDistributionTokens(
    val labelWeight: Float,
    val trackWeight: Float,
    val amountWeight: Float,
    val minFillFraction: Float,
)

data class StatsComparisonChartTokens(
    val height: Dp,
    val verticalPadding: Dp,
    val innerGap: Dp,
    val groupWidthFraction: Float,
    val minBarWidth: Dp,
    val maxBarWidth: Dp,
    val minBarHeight: Dp,
    val guideStrokeWidth: Dp,
    val guideRatios: List<Float>,
    val guideAlpha: Float,
    val barAlpha: Float,
)

private fun paperStatsTokens(): StatsTokens =
    StatsTokens(
        surface = StatsSurfaceTokens(
            hero = StatsSurfaceStyleTokens(radius = 18.dp, topAlpha = 0.42f, bottomAlpha = 0.12f, borderAlpha = 0.06f),
            section = StatsSurfaceStyleTokens(radius = 0.dp, topAlpha = 0f, bottomAlpha = 0f, borderAlpha = 0f),
        ),
        control = StatsControlTokens(
            height = 34.dp,
            horizontalPadding = 12.dp,
            selectedAlpha = 0.72f,
            unselectedAlpha = 0.44f,
            borderAlpha = 0.18f,
        ),
        chart = StatsChartTokens(
            overviewHeight = 92.dp,
            monthlyHeight = 112.dp,
            recentHeight = 92.dp,
            distributionHeight = 14.dp,
            distribution = defaultStatsDistributionTokens(),
            guideAlpha = 0.34f,
            quietAlpha = 0.62f,
            emphasisAlpha = 0.92f,
            comparison = defaultStatsComparisonChartTokens(guideAlpha = 0.26f, barAlpha = 0.84f),
        ),
    )

private fun monoStatsTokens(): StatsTokens =
    StatsTokens(
        surface = StatsSurfaceTokens(
            hero = StatsSurfaceStyleTokens(radius = 18.dp, topAlpha = 0.40f, bottomAlpha = 0.12f, borderAlpha = 0.05f),
            section = StatsSurfaceStyleTokens(radius = 0.dp, topAlpha = 0f, bottomAlpha = 0f, borderAlpha = 0f),
        ),
        control = StatsControlTokens(
            height = 34.dp,
            horizontalPadding = 12.dp,
            selectedAlpha = 0.66f,
            unselectedAlpha = 0.40f,
            borderAlpha = 0.16f,
        ),
        chart = StatsChartTokens(
            overviewHeight = 92.dp,
            monthlyHeight = 112.dp,
            recentHeight = 92.dp,
            distributionHeight = 14.dp,
            distribution = defaultStatsDistributionTokens(),
            guideAlpha = 0.30f,
            quietAlpha = 0.58f,
            emphasisAlpha = 0.90f,
            comparison = defaultStatsComparisonChartTokens(guideAlpha = 0.24f, barAlpha = 0.82f),
        ),
    )

private fun midnightStatsTokens(): StatsTokens =
    StatsTokens(
        surface = StatsSurfaceTokens(
            hero = StatsSurfaceStyleTokens(radius = 18.dp, topAlpha = 0.28f, bottomAlpha = 0.08f, borderAlpha = 0.06f),
            section = StatsSurfaceStyleTokens(radius = 0.dp, topAlpha = 0f, bottomAlpha = 0f, borderAlpha = 0f),
        ),
        control = StatsControlTokens(
            height = 34.dp,
            horizontalPadding = 12.dp,
            selectedAlpha = 0.42f,
            unselectedAlpha = 0.16f,
            borderAlpha = 0.16f,
        ),
        chart = StatsChartTokens(
            overviewHeight = 92.dp,
            monthlyHeight = 112.dp,
            recentHeight = 92.dp,
            distributionHeight = 14.dp,
            distribution = defaultStatsDistributionTokens(),
            guideAlpha = 0.34f,
            quietAlpha = 0.62f,
            emphasisAlpha = 0.92f,
            comparison = defaultStatsComparisonChartTokens(guideAlpha = 0.28f, barAlpha = 0.84f),
        ),
    )

private fun defaultStatsDistributionTokens(): StatsDistributionTokens =
    StatsDistributionTokens(
        labelWeight = 0.92f,
        trackWeight = 1.46f,
        amountWeight = 1.08f,
        minFillFraction = 0.08f,
    )

private fun defaultStatsComparisonChartTokens(
    guideAlpha: Float,
    barAlpha: Float,
): StatsComparisonChartTokens =
    StatsComparisonChartTokens(
        height = 138.dp,
        verticalPadding = 8.dp,
        innerGap = 3.dp,
        groupWidthFraction = 0.62f,
        minBarWidth = 4.dp,
        maxBarWidth = 12.dp,
        minBarHeight = 6.dp,
        guideStrokeWidth = 1.dp,
        guideRatios = listOf(0.5f, 1f),
        guideAlpha = guideAlpha,
        barAlpha = barAlpha,
    )
