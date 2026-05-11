package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.DeepHeroPanel
import com.ticketbox.ui.components.formatAmount

@Composable
internal fun StatsOverviewCard(
    stats: MonthlyStats,
    recent7DaysAmountCents: Long,
    comparison: MonthComparison?,
) {
    DeepHeroPanel {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "本月支出",
                color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.82f),
                style = MaterialTheme.typography.labelLarge,
            )
            Text(
                text = formatAmount(stats.totalAmountCents),
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.onPrimary,
            )
            Text(
                text = "${stats.count} 笔 · 最近 7 天 ${formatAmount(recent7DaysAmountCents)}",
                color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.80f),
                style = MaterialTheme.typography.bodyMedium,
            )
            HeroTrendLine()
            comparison?.let(::monthComparisonText)?.let { contextLine ->
                Text(
                    text = contextLine,
                    color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.76f),
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun HeroTrendLine() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        listOf(0.30f, 0.42f, 0.35f, 0.68f, 0.50f, 0.46f, 0.78f, 0.58f, 0.48f, 0.64f).forEachIndexed { index, weight ->
            Box(
                modifier = Modifier
                    .weight(weight)
                    .height(if (index == 6) 10.dp else 7.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(MaterialTheme.colorScheme.onPrimary.copy(alpha = if (index == 6) 0.95f else 0.46f)),
            )
        }
    }
}

internal fun monthComparisonText(comparison: MonthComparison): String {
    if (comparison.previousAmountCents == 0L) {
        return if (comparison.currentAmountCents == 0L) {
            "暂无可对比记录"
        } else {
            "上月暂无可比"
        }
    }
    val delta = comparison.deltaAmountCents
    if (delta == 0L) return "和上月持平"
    val direction = if (delta > 0L) "多花" else "少花"
    val percent = comparison.percentChange
        ?.let { value -> " · ${if (value > 0) "+" else ""}$value%" }
        .orEmpty()
    return "比上月$direction ${formatAmount(kotlin.math.abs(delta))}$percent"
}
