package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryInsight
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun CategoryStructureCard(
    categories: List<CategoryStats>,
    totalAmountCents: Long,
    insight: CategoryInsight?,
    // §三报表钻取:分类行点击 → 账本带筛选打开。null=行不可点(预览/无宿主场景原样)。
    onCategoryClick: ((String) -> Unit)? = null,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val topCategories = categories.sortedByDescending { it.amountCents }.take(5)
    val topCategory = topCategories.firstOrNull()
    AppGlassCard(containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                CategoryDonut(
                    categories = topCategories,
                    totalAmountCents = totalAmountCents,
                )
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        stringResource(R.string.stats_category_structure_title),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = AppTextHierarchy.heading.weight,
                    )
                    Text(
                        text = if (topCategory != null) {
                            stringResource(R.string.stats_category_structure_top, topCategory.category)
                        } else {
                            stringResource(R.string.stats_category_structure_empty)
                        },
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = if (insight != null) {
                            stringResource(
                                R.string.stats_category_structure_insight,
                                insight.topSharePercent,
                                insight.categoryCount,
                            )
                        } else {
                            stringResource(R.string.stats_category_structure_count, categories.size)
                        },
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                topCategories.forEachIndexed { index, category ->
                    CategoryStructureBarRow(
                        category = category,
                        totalAmountCents = totalAmountCents,
                        index = index,
                        currencyDisplay = currencyDisplay,
                        onClick = onCategoryClick?.let { handler -> { handler(category.category) } },
                    )
                }
            }
            if (onCategoryClick != null) {
                Text(
                    text = stringResource(R.string.stats_category_structure_drill_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        }
    }
}

@Composable
private fun CategoryStructureBarRow(
    category: CategoryStats,
    totalAmountCents: Long,
    index: Int,
    currencyDisplay: CurrencyDisplay,
    onClick: (() -> Unit)? = null,
) {
    val colors = statsCategoryColors()
    val percent = if (totalAmountCents > 0L) {
        (category.amountCents * 100 / totalAmountCents).toInt()
    } else {
        0
    }
    val progress = if (totalAmountCents > 0L) {
        (category.amountCents.toFloat() / totalAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    Column(
        modifier = if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(10.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(colors[index % colors.size]),
            )
            Text(
                text = category.category,
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = formatDisplayAmount(category.amountCents, currencyDisplay),
                style = MaterialTheme.typography.labelLarge.tabularNum(),
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = AppTextHierarchy.body.weight,
            )
            Text(
                text = stringResource(R.string.stats_category_structure_percent, percent),
                modifier = Modifier.width(38.dp),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(7.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.10f)),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(progress)
                    .height(7.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(colors[index % colors.size]),
            )
        }
    }
}

@Composable
private fun CategoryDonut(
    categories: List<CategoryStats>,
    totalAmountCents: Long,
) {
    val colors = statsCategoryColors()
    // 空态环走 ChartTokens.empty(每皮肤一套),此前硬编码 Color.LightGray 在 midnight 深底卡上是刺眼浅环。
    val emptyRingColor = LocalChartTokens.current.empty
    Canvas(modifier = Modifier.size(92.dp)) {
        val stroke = Stroke(width = 16.dp.toPx(), cap = StrokeCap.Round)
        if (totalAmountCents <= 0L || categories.isEmpty()) {
            drawArc(
                color = emptyRingColor,
                startAngle = -90f,
                sweepAngle = 360f,
                useCenter = false,
                style = stroke,
            )
            return@Canvas
        }
        var startAngle = -90f
        categories.forEachIndexed { index, category ->
            val sweep = 360f * (category.amountCents.toFloat() / totalAmountCents.toFloat()).coerceIn(0f, 1f)
            drawArc(
                color = colors[index % colors.size],
                startAngle = startAngle,
                sweepAngle = sweep,
                useCenter = false,
                style = stroke,
            )
            startAngle += sweep
        }
    }
}

@Composable
private fun statsCategoryColors(): List<Color> {
    val visuals = LocalThemeVisuals.current
    return listOf(
        visuals.primary,
        visuals.accent,
        visuals.warningTint,
        visuals.primaryDark.copy(alpha = 0.70f),
        visuals.shadowTint.copy(alpha = 0.55f),
    )
}
