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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.TagStats
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun CategoryStructureCard(
    categories: List<CategoryStats>,
    tags: List<TagStats>,
    totalAmountCents: Long,
    onCategoryClick: ((String) -> Unit)? = null,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val visuals = LocalThemeVisuals.current
    val sortedCategories = remember(categories) {
        categories
            .filter { it.amountCents > 0L && it.count > 0 }
            .sortedByDescending { it.amountCents }
    }
    val visibleTags = remember(tags) {
        tags
            .filter { it.amountCents > 0L && it.count > 0 }
            .sortedByDescending { it.amountCents }
            .take(6)
    }
    val topCategories = remember(sortedCategories) { sortedCategories.take(5) }
    val topCategory = topCategories.firstOrNull()
    val categoryCount = sortedCategories.size
    val topShareLabel = topCategory?.let { categoryShareLabel(it.amountCents, totalAmountCents) }
    val topAmountLabel = topCategory?.let { formatDisplayAmount(it.amountCents, currencyDisplay) }
    val otherCount = (categoryCount - 1).coerceAtLeast(0)
    val otherAmountCents = remember(sortedCategories) { sortedCategories.drop(1).sumOf { it.amountCents } }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(
                stringResource(R.string.stats_category_structure_title),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = AppTextHierarchy.body.weight,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = if (topCategory != null) {
                        stringResource(R.string.stats_category_structure_top, topCategory.category)
                    } else {
                        stringResource(R.string.stats_category_structure_empty)
                    },
                    modifier = Modifier.weight(1f),
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                topAmountLabel?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.titleSmall.tabularNum(),
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                    )
                }
            }
            Text(
                text = if (topShareLabel != null) {
                    stringResource(
                        R.string.stats_category_structure_insight,
                        topShareLabel,
                        categoryCount,
                    )
                } else {
                    stringResource(R.string.stats_category_structure_count, categoryCount)
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingSmall),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CategoryDonut(
                categories = topCategories,
                totalAmountCents = totalAmountCents,
            )
            if (topCategory != null && otherCount > 0 && otherAmountCents > 0L) {
                Text(
                    text = stringResource(
                        R.string.stats_category_structure_remainder,
                        otherCount,
                        formatDisplayAmount(otherAmountCents, currencyDisplay),
                    ),
                    modifier = Modifier.weight(1f),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
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
        if (visibleTags.isNotEmpty()) {
            HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.heavy))
            TagDistributionSection(
                tags = visibleTags,
                totalAmountCents = totalAmountCents,
                currencyDisplay = currencyDisplay,
            )
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
    val percentLabel = categoryShareLabel(category.amountCents, totalAmountCents)
    val progress = if (totalAmountCents > 0L) {
        (category.amountCents.toFloat() / totalAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    Column(
        modifier = if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(AppSpacing.contentGap)
                    .clip(RoundedCornerShape(AppRadius.pill))
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
                text = percentLabel,
                modifier = Modifier.width(44.dp),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(AppSpacing.smallGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.faint)),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(progress)
                    .height(AppSpacing.smallGap)
                    .clip(RoundedCornerShape(AppRadius.pill))
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
    val emptyTrack = LocalChartTokens.current.empty
    Canvas(
        modifier = Modifier
            .size(92.dp)
            .clearAndSetSemantics {},
    ) {
        val stroke = Stroke(width = 16.dp.toPx(), cap = StrokeCap.Round)
        if (totalAmountCents <= 0L || categories.isEmpty()) {
            drawArc(
                color = emptyTrack,
                startAngle = -90f,
                sweepAngle = 360f,
                useCenter = false,
                style = stroke,
            )
            return@Canvas
        }
        drawArc(
            color = emptyTrack.copy(alpha = 0.34f),
            startAngle = -90f,
            sweepAngle = 360f,
            useCenter = false,
            style = stroke,
        )
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
private fun TagDistributionSection(
    tags: List<TagStats>,
    totalAmountCents: Long,
    currencyDisplay: CurrencyDisplay,
) {
    val visuals = LocalThemeVisuals.current
    val showBars = remember(tags) {
        val firstAmount = tags.firstOrNull()?.amountCents
        tags.size > 1 && firstAmount != null && tags.any { it.amountCents != firstAmount }
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(
                stringResource(R.string.stats_tag_distribution_title),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.stats_tag_distribution_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        tags.forEachIndexed { index, tag ->
            if (index > 0) {
                HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.medium))
            }
            TagStatsRow(
                tag = tag,
                totalAmountCents = totalAmountCents,
                colorIndex = index,
                currencyDisplay = currencyDisplay,
                showBar = showBars,
            )
        }
    }
}

@Composable
private fun TagStatsRow(
    tag: TagStats,
    totalAmountCents: Long,
    colorIndex: Int,
    currencyDisplay: CurrencyDisplay,
    showBar: Boolean,
) {
    val colors = statsCategoryColors()
    val color = colors[(colorIndex + 1) % colors.size]
    val progress = if (totalAmountCents > 0L) {
        (tag.amountCents.toFloat() / totalAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val percent = if (totalAmountCents > 0L) {
        (tag.amountCents * 100 / totalAmountCents).toInt().coerceIn(0, 100)
    } else {
        0
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TagStatsContentRow(
            tag = tag,
            percent = percent,
            currencyDisplay = currencyDisplay,
            color = color,
        )
        if (showBar) {
            TagStatsBar(progress = progress, color = color)
        }
    }
}

@Composable
private fun TagStatsContentRow(
    tag: TagStats,
    percent: Int,
    currencyDisplay: CurrencyDisplay,
    color: Color,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(AppSpacing.smallGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(color),
        )
        Text(
            text = stringResource(R.string.stats_tag_distribution_row_label, tag.tag),
            modifier = Modifier.weight(1f),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = formatDisplayAmount(tag.amountCents, currencyDisplay),
            style = MaterialTheme.typography.labelLarge.tabularNum(),
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = AppTextHierarchy.body.weight,
        )
        Text(
            text = stringResource(R.string.stats_tag_distribution_percent_count, percent, tag.count),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
        )
    }
}

@Composable
private fun TagStatsBar(progress: Float, color: Color) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(AppSpacing.miniGap)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.faint)),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(progress)
                .height(AppSpacing.miniGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(color),
        )
    }
}

@Composable
private fun categoryShareLabel(
    amountCents: Long,
    totalAmountCents: Long,
): String {
    if (amountCents <= 0L || totalAmountCents <= 0L) {
        return stringResource(R.string.stats_category_structure_percent, 0)
    }
    val share = amountCents.toDouble() / totalAmountCents.toDouble() * 100.0
    return when {
        share < 1.0 -> stringResource(R.string.stats_category_structure_share_less_than_one)
        amountCents < totalAmountCents && share > 99.0 -> {
            stringResource(R.string.stats_category_structure_share_more_than_ninety_nine)
        }
        else -> stringResource(R.string.stats_category_structure_percent, share.toInt().coerceIn(1, 100))
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
