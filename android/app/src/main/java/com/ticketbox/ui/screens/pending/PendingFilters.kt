package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.annotation.StringRes
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppGlassCard

/**
 * Needs Review filter — UI-only client-side filter over already-loaded pending items.
 * 不触碰 Retrofit/Room；只在已加载的列表上做筛选。
 */
internal enum class NeedsReviewFilter(@StringRes val labelRes: Int) {
    All(R.string.pending_filter_label_all),
    NeedsAmount(R.string.pending_filter_label_needs_amount),
    NeedsMerchant(R.string.pending_filter_label_needs_merchant),
    Duplicate(R.string.pending_filter_label_duplicate),
    ReadyToConfirm(R.string.pending_filter_label_ready_to_confirm),
}

internal fun applyNeedsReviewFilter(items: List<Expense>, filter: NeedsReviewFilter): List<Expense> {
    return when (filter) {
        NeedsReviewFilter.All -> items
        NeedsReviewFilter.NeedsAmount -> items.filter { it.amountCents == null }
        NeedsReviewFilter.NeedsMerchant -> items.filter { it.merchant.isNullOrBlank() }
        NeedsReviewFilter.Duplicate -> items.filter { it.duplicateStatus == "suspected" }
        NeedsReviewFilter.ReadyToConfirm -> items.filter {
            it.amountCents != null && !it.merchant.isNullOrBlank() && it.duplicateStatus != "suspected"
        }
    }
}

@Composable
internal fun NeedsReviewFilterBar(
    selected: NeedsReviewFilter,
    allCount: Int,
    needsAmountCount: Int,
    needsMerchantCount: Int,
    duplicateCount: Int,
    readyToConfirmCount: Int,
    onSelect: (NeedsReviewFilter) -> Unit,
) {
    val scroll = rememberScrollState()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(scroll)
            .padding(horizontal = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val countOf: (NeedsReviewFilter) -> Int = { f ->
            when (f) {
                NeedsReviewFilter.All -> allCount
                NeedsReviewFilter.NeedsAmount -> needsAmountCount
                NeedsReviewFilter.NeedsMerchant -> needsMerchantCount
                NeedsReviewFilter.Duplicate -> duplicateCount
                NeedsReviewFilter.ReadyToConfirm -> readyToConfirmCount
            }
        }
        NeedsReviewFilter.values().forEach { f ->
            AppFilterChip(
                label = "${stringResource(f.labelRes)} ${countOf(f)}",
                selected = f == selected,
                onClick = { onSelect(f) },
            )
        }
    }
}

@Composable
internal fun NeedsReviewEmptyFilterCard(filter: NeedsReviewFilter) {
    AppGlassCard(containerAlpha = 0.92f) {
        Column(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 18.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
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
}
