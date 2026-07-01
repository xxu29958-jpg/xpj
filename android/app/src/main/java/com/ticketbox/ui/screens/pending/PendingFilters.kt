package com.ticketbox.ui.screens.pending

import androidx.annotation.StringRes
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.isPendingReadyToConfirmDirectly
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

/**
 * Needs Review filter — UI-only client-side filter over already-loaded pending items.
 * 不触碰 Retrofit/Room；只在已加载的列表上做筛选。
 */
internal enum class NeedsReviewFilter(@param:StringRes val labelRes: Int) {
    All(R.string.pending_filter_label_all),
    NeedsAmount(R.string.pending_filter_label_needs_amount),
    NeedsMerchant(R.string.pending_filter_label_needs_merchant),
    Duplicate(R.string.pending_filter_label_duplicate),
    ReadyToConfirm(R.string.pending_filter_label_ready_to_confirm),
}

internal data class PendingQueueCounts(
    val all: Int,
    val needsAmount: Int,
    val needsMerchant: Int,
    val duplicate: Int,
    val readyToConfirm: Int,
)

internal fun applyNeedsReviewFilter(items: List<Expense>, filter: NeedsReviewFilter): List<Expense> {
    return when (filter) {
        NeedsReviewFilter.All -> items
        NeedsReviewFilter.NeedsAmount -> items.filter { it.amountCents == null }
        NeedsReviewFilter.NeedsMerchant -> items.filter { it.merchant.isNullOrBlank() }
        NeedsReviewFilter.Duplicate -> items.filter { it.duplicateStatus == DuplicateStatusValues.SUSPECTED }
        NeedsReviewFilter.ReadyToConfirm -> items.filter { it.isPendingReadyToConfirmDirectly() }
    }
}

@Composable
internal fun NeedsReviewFilterBar(
    selected: NeedsReviewFilter,
    counts: PendingQueueCounts,
    onSelect: (NeedsReviewFilter) -> Unit,
) {
    val scroll = rememberScrollState()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(scroll)
            .padding(horizontal = AppSpacing.tinyGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val countOf: (NeedsReviewFilter) -> Int = { f ->
            when (f) {
                NeedsReviewFilter.All -> counts.all
                NeedsReviewFilter.NeedsAmount -> counts.needsAmount
                NeedsReviewFilter.NeedsMerchant -> counts.needsMerchant
                NeedsReviewFilter.Duplicate -> counts.duplicate
                NeedsReviewFilter.ReadyToConfirm -> counts.readyToConfirm
            }
        }
        NeedsReviewFilter.values().forEach { f ->
            AppFilterChip(
                label = stringResource(
                    R.string.pending_filter_chip_label,
                    stringResource(f.labelRes),
                    countOf(f),
                ),
                selected = f == selected,
                onClick = { onSelect(f) },
            )
        }
    }
}

@Composable
internal fun NeedsReviewEmptyFilterCard(filter: NeedsReviewFilter) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
        Text(
            text = stringResource(R.string.pending_filter_empty_title, stringResource(filter.labelRes)),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = stringResource(R.string.pending_filter_empty_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
