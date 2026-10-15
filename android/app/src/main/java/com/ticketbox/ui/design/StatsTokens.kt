package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin

data class StatsSurfaceTokens(
    val section: StatsSurfaceStyleTokens,
)

data class StatsSurfaceStyleTokens(
    val radius: Dp,
    val topAlpha: Float,
    val borderAlpha: Float,
)

data class StatsControlTokens(
    val height: Dp,
    val borderWidth: Dp,
    val horizontalPadding: Dp,
    val selectedAlpha: Float,
    val unselectedAlpha: Float,
    val borderAlpha: Float,
)

data class StatsChartTokens(
    val overviewHeight: Dp,
    val monthlyHeight: Dp,
    val recentHeight: Dp,
    val minimumRangeLabelWidth: Dp,
    val distributionHeight: Dp,
    val distribution: StatsDistributionTokens,
    val guideAlpha: Float,
    val quietAlpha: Float,
    val emphasisAlpha: Float,
)

data class StatsTokens(
    val surface: StatsSurfaceTokens,
    val control: StatsControlTokens,
    val chart: StatsChartTokens,
)

val LocalStatsTokens = compositionLocalOf { statsTokensForSkin(AppSkin.Default) }

fun statsTokensForSkin(skin: AppSkin): StatsTokens = when (skin) {
    AppSkin.Paper -> paperStatsTokens()
    AppSkin.Midnight -> midnightStatsTokens()
}

data class StatsDistributionTokens(
    val labelWeight: Float,
    val trackWeight: Float,
    val amountWeight: Float,
    val minFillFraction: Float,
)

private fun paperStatsTokens(): StatsTokens =
    StatsTokens(
        surface = StatsSurfaceTokens(
            section = StatsSurfaceStyleTokens(radius = 12.dp, topAlpha = 1f, borderAlpha = 0.86f),
        ),
        control = StatsControlTokens(
            height = 34.dp,
            borderWidth = 1.dp,
            horizontalPadding = 12.dp,
            selectedAlpha = 1f,
            unselectedAlpha = 1f,
            borderAlpha = 0.58f,
        ),
        chart = StatsChartTokens(
            overviewHeight = 92.dp,
            monthlyHeight = 112.dp,
            recentHeight = 92.dp,
            minimumRangeLabelWidth = StatsRangeLabelMinimumWidth,
            distributionHeight = 14.dp,
            distribution = defaultStatsDistributionTokens(),
            guideAlpha = 0.34f,
            quietAlpha = 0.62f,
            emphasisAlpha = 0.92f,
        ),
    )

private fun midnightStatsTokens(): StatsTokens =
    StatsTokens(
        surface = StatsSurfaceTokens(
            section = StatsSurfaceStyleTokens(radius = 12.dp, topAlpha = 1f, borderAlpha = 0.86f),
        ),
        control = StatsControlTokens(
            height = 34.dp,
            borderWidth = 1.dp,
            horizontalPadding = 12.dp,
            selectedAlpha = 1f,
            unselectedAlpha = 1f,
            borderAlpha = 0.56f,
        ),
        chart = StatsChartTokens(
            overviewHeight = 92.dp,
            monthlyHeight = 112.dp,
            recentHeight = 92.dp,
            minimumRangeLabelWidth = StatsRangeLabelMinimumWidth,
            distributionHeight = 14.dp,
            distribution = defaultStatsDistributionTokens(),
            guideAlpha = 0.34f,
            quietAlpha = 0.62f,
            emphasisAlpha = 0.92f,
        ),
    )

private fun defaultStatsDistributionTokens(): StatsDistributionTokens =
    StatsDistributionTokens(
        labelWeight = 0.92f,
        trackWeight = 1.46f,
        amountWeight = 1.08f,
        minFillFraction = 0.08f,
    )

private val StatsRangeLabelMinimumWidth = 60.dp
