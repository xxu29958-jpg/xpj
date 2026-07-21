package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.DataQualityLoadState

@Composable
internal fun DataQualityEntryCard(
    summary: DataQualitySummary?,
    loadState: DataQualityLoadState,
    onClick: () -> Unit,
) {
    AppListRow(onClick = onClick) {
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(R.string.stats_data_quality_entry_title),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = dataQualityEntrySubtitle(summary, loadState),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.align(Alignment.CenterVertically),
        )
    }
}

@Composable
private fun dataQualityEntrySubtitle(
    summary: DataQualitySummary?,
    loadState: DataQualityLoadState,
): String = when {
    summary != null && summary.hasDataQualityAttention() -> {
        val counts = summary.toDataQualityAttentionCounts()
        stringResource(
            R.string.stats_data_quality_entry_attention,
            counts.pendingTotal,
            counts.missingCategory,
            counts.suspectedDuplicates,
            counts.confirmedWithoutImage,
        )
    }
    summary != null -> stringResource(R.string.stats_data_quality_entry_clear)
    loadState == DataQualityLoadState.Failed ->
        stringResource(R.string.stats_data_quality_entry_unavailable)
    else -> stringResource(R.string.stats_data_quality_entry_loading)
}

internal fun DataQualitySummary.hasDataQualityAttention(): Boolean =
    pendingTotal > 0 ||
        missingCategory > 0 ||
        suspectedDuplicates > 0 ||
        confirmedWithoutImage > 0

internal data class DataQualityAttentionCounts(
    val pendingTotal: Int,
    val missingCategory: Int,
    val suspectedDuplicates: Int,
    val confirmedWithoutImage: Int,
)

internal fun DataQualitySummary.toDataQualityAttentionCounts(): DataQualityAttentionCounts =
    DataQualityAttentionCounts(
        pendingTotal = pendingTotal,
        missingCategory = missingCategory,
        suspectedDuplicates = suspectedDuplicates,
        confirmedWithoutImage = confirmedWithoutImage,
    )
