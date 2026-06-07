package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.StatsSource

@Composable
internal fun StatsOverviewCard(
    stats: MonthlyStats,
    recent7DaysAmountCents: Long,
    comparison: MonthComparison?,
    dailyTrend: List<DailySpend> = emptyList(),
    statsSource: StatsSource = StatsSource.Backend,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    AppContentCard(
        contentPadding = PaddingValues(
            horizontal = AppSpacing.cardPaddingSmall,
            vertical = AppSpacing.cardPaddingTight,
        ),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                modifier = Modifier.weight(1f),
                text = stringResource(R.string.stats_overview_month_spend_label),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (statsSource == StatsSource.LocalFallback) {
                Text(
                    text = stringResource(R.string.stats_overview_local_estimate_badge),
                    modifier = Modifier
                        .clip(RoundedCornerShape(AppRadius.pill))
                        .background(MaterialTheme.colorScheme.secondaryContainer)
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                    color = MaterialTheme.colorScheme.onSecondaryContainer,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.Bottom,
        ) {
            Text(
                modifier = Modifier.weight(1f),
                text = formatDisplayAmount(stats.totalAmountCents, currencyDisplay),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleLarge.copy(
                    fontSize = AppTypography.amountLarge.size,
                    lineHeight = 38.sp,
                    letterSpacing = 0.sp,
                    fontWeight = AppTypography.amountLarge.weight,
                ).tabularNum(),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            comparison?.let { MonthDeltaPill(it, currencyDisplay) }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        ) {
            CompactMetric(
                label = stringResource(R.string.stats_overview_count_label),
                value = stringResource(R.string.stats_overview_count_value, stats.count),
                modifier = Modifier.weight(1f),
            )
            CompactMetric(
                label = stringResource(R.string.stats_overview_recent7_label),
                value = formatDisplayAmount(recent7DaysAmountCents, currencyDisplay),
                modifier = Modifier.weight(1f),
            )
        }
        // 真趋势线：用最近若干天的实际支出渲染面积折线（替换之前的 hardcoded 0.30/0.42 占位）
        HeroSparkline(points = dailyTrend)
    }
}
@Composable
private fun MonthDeltaPill(
    comparison: MonthComparison,
    currencyDisplay: CurrencyDisplay,
) {
    if (comparison.previousAmountCents == 0L) return
    val visuals = LocalThemeVisuals.current
    val delta = comparison.deltaAmountCents
    val (label, tint) = when {
        delta == 0L -> stringResource(R.string.stats_overview_delta_flat) to MaterialTheme.colorScheme.onSurfaceVariant
        delta > 0L -> {
            val percent = comparison.percentChange?.let { " +${it}%" }.orEmpty()
            "↑ ${formatDisplayAmount(kotlin.math.abs(delta), currencyDisplay)}$percent" to visuals.warningTint
        }
        else -> {
            val percent = comparison.percentChange?.let { " ${kotlin.math.abs(it)}%" }.orEmpty()
            "↓ ${formatDisplayAmount(kotlin.math.abs(delta), currencyDisplay)}$percent" to visuals.textDefault
        }
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(tint.copy(alpha = 0.14f))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) {
        Text(
            text = label,
            color = tint,
            style = MaterialTheme.typography.labelSmall.tabularNum(),
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun CompactMetric(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/**
 * Hero sparkline —— 用 Compose Canvas 自绘的微型趋势折线 + 半透明面积填充。
 *
 * 设计取舍：
 * - 不引 Vico 这种"大图"。Hero overview 的趋势线只是一个气压计性质的暗示，
 *   像「最近怎么样」的余光指示，不应该有坐标轴 / tooltip / 图例。
 * - 至少要 2 个点才画线，1 个点画一条横线，0 个点画一条 placeholder 虚线
 *   带"无数据"字样不必要 —— overview 卡里挤一段就够了。
 * - 高度固定 28dp。再大会跟 hero amount 抢视觉权重；再小看不清。
 * - 颜色用 ThemeVisuals.primary，与上面 amount 一致；面积透明度 0.16。
 */
@Composable
private fun HeroSparkline(points: List<DailySpend>) {
    val visuals = LocalThemeVisuals.current
    val lineColor = visuals.primary
    val fillColor = visuals.primary.copy(alpha = 0.16f)
    val placeholderColor = visuals.coolMist.copy(alpha = 0.5f)

    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(28.dp),
    ) {
        val w = size.width
        val h = size.height
        if (points.isEmpty()) {
            // 占位虚线：横向中线，告诉用户「这里会出现趋势」
            drawLine(
                color = placeholderColor,
                start = Offset(0f, h / 2f),
                end = Offset(w, h / 2f),
                strokeWidth = 1.dp.toPx(),
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 8f)),
            )
            return@Canvas
        }
        val amounts = points.map { it.amountCents.coerceAtLeast(0L).toFloat() }
        val maxV = amounts.maxOrNull() ?: 0f
        val minV = 0f
        // 顶部留 3dp 空气，底部留 2dp（折线不能贴顶/底）
        val top = 3.dp.toPx()
        val bottom = h - 2.dp.toPx()
        val plotH = bottom - top
        val stepX = if (amounts.size > 1) w / (amounts.size - 1).toFloat() else 0f
        fun yFor(value: Float): Float {
            if (maxV == minV) return bottom
            val ratio = (value - minV) / (maxV - minV)
            return bottom - ratio * plotH
        }

        if (amounts.size == 1) {
            // 单点：画一条水平细线，给「有数据但不够展开」的弱视觉提示
            val y = yFor(amounts[0])
            drawLine(
                color = lineColor.copy(alpha = 0.6f),
                start = Offset(0f, y),
                end = Offset(w, y),
                strokeWidth = 1.5.dp.toPx(),
            )
            return@Canvas
        }

        // 面积 path：起点 (0, bottom) → 折线 → 终点 (w, bottom) → 闭合
        val areaPath = Path().apply {
            moveTo(0f, bottom)
            amounts.forEachIndexed { i, v ->
                lineTo(i * stepX, yFor(v))
            }
            lineTo(w, bottom)
            close()
        }
        drawPath(
            path = areaPath,
            brush = Brush.verticalGradient(
                colors = listOf(fillColor, fillColor.copy(alpha = 0f)),
                startY = top,
                endY = bottom,
            ),
        )

        // 折线本体
        val linePath = Path().apply {
            amounts.forEachIndexed { i, v ->
                val x = i * stepX
                val y = yFor(v)
                if (i == 0) moveTo(x, y) else lineTo(x, y)
            }
        }
        drawPath(
            path = linePath,
            color = lineColor.copy(alpha = 0.88f),
            style = Stroke(width = 1.6.dp.toPx()),
        )

        // 最后一个点画一个小圆点（最新一天）
        val lastIndex = amounts.lastIndex
        drawCircle(
            color = lineColor,
            radius = 2.6.dp.toPx(),
            center = Offset(lastIndex * stepX, yFor(amounts.last())),
        )
    }
}
