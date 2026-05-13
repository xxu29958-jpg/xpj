package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.TagStats
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun TagStatsCard(
    tags: List<TagStats>,
    totalAmountCents: Long,
) {
    val visibleTags = tags
        .filter { it.amountCents > 0L && it.count > 0 }
        .sortedByDescending { it.amountCents }
        .take(6)
    if (visibleTags.isEmpty()) {
        return
    }

    val visuals = LocalThemeVisuals.current
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("标签分布", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Black)
                Text(
                    text = "按本月已确认账单的标签聚合",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            visibleTags.forEachIndexed { index, tag ->
                if (index > 0) {
                    HorizontalDivider(color = visuals.chipUnselected.copy(alpha = 0.70f))
                }
                TagStatsRow(
                    tag = tag,
                    totalAmountCents = totalAmountCents,
                    colorIndex = index,
                )
            }
        }
    }
}

@Composable
private fun TagStatsRow(
    tag: TagStats,
    totalAmountCents: Long,
    colorIndex: Int,
) {
    val colors = tagStatsColors()
    val progress = if (totalAmountCents > 0L) {
        (tag.amountCents.toFloat() / totalAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val percent = if (totalAmountCents > 0L) {
        (tag.amountCents * 100 / totalAmountCents).toInt()
    } else {
        0
    }
    Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(9.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(colors[colorIndex % colors.size]),
            )
            Text(
                text = "#${tag.tag}",
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = formatAmount(tag.amountCents),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "$percent% · ${tag.count} 笔",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.10f)),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(progress)
                    .height(6.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(colors[colorIndex % colors.size]),
            )
        }
    }
}

@Composable
private fun tagStatsColors(): List<Color> {
    val visuals = LocalThemeVisuals.current
    return listOf(
        visuals.accent,
        visuals.primary,
        visuals.warningTint,
        visuals.primaryDark.copy(alpha = 0.70f),
        visuals.shadowTint.copy(alpha = 0.55f),
    )
}
