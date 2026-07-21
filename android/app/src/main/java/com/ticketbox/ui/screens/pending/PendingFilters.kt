package com.ticketbox.ui.screens.pending

import androidx.annotation.StringRes
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

/**
 * Needs Review filter — UI-only client-side filter over already-loaded pending items.
 * 不触碰 Retrofit/Room；只在已加载的列表上做筛选。
 */
enum class NeedsReviewFilter(@param:StringRes val labelRes: Int) {
    All(R.string.pending_filter_label_all),
    NeedsAmount(R.string.pending_filter_label_needs_amount),
    NeedsMerchant(R.string.pending_filter_label_needs_merchant),
    NeedsCategory(R.string.pending_filter_label_needs_category),
    Duplicate(R.string.pending_filter_label_duplicate),
    ReadyToConfirm(R.string.pending_filter_label_ready_to_confirm),
}

internal enum class InboxSection(@param:StringRes val labelRes: Int) {
    Pending(R.string.inbox_section_pending),
    Duplicates(R.string.inbox_section_duplicates),
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun InboxActionLinks(
    onOpenProcessing: () -> Unit,
    onOpenRepaymentReview: () -> Unit,
    onOpenDataQuality: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = stringResource(R.string.inbox_action_links_title),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        AppCompactChips {
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                AppFilterChip(
                    label = stringResource(R.string.inbox_processing_entry_title),
                    selected = false,
                    onClick = onOpenProcessing,
                )
                AppFilterChip(
                    label = stringResource(R.string.relations_repayment_review),
                    selected = false,
                    onClick = onOpenRepaymentReview,
                )
                AppFilterChip(
                    label = stringResource(R.string.stats_data_quality_entry_title),
                    selected = false,
                    onClick = onOpenDataQuality,
                )
            }
        }
    }
}

internal data class PendingQueueCounts(
    val all: Int,
    val needsAmount: Int,
    val needsMerchant: Int,
    val duplicate: Int,
    val readyToConfirm: Int,
    val needsCategory: Int = 0,
    val needsInformation: Int = 0,
)

internal fun visibleNeedsReviewFilters(
    counts: PendingQueueCounts,
    selected: NeedsReviewFilter,
): List<NeedsReviewFilter> {
    val visible = mutableListOf(NeedsReviewFilter.All)
    pendingSignalFilters.forEach { filter ->
        if (counts.countFor(filter) > 0) {
            visible += filter
        }
    }
    if (selected != NeedsReviewFilter.Duplicate && selected !in visible) {
        visible += selected
    }
    return visible
}

internal fun shouldShowNeedsReviewFilterBar(
    counts: PendingQueueCounts,
    selected: NeedsReviewFilter,
): Boolean {
    if (counts.all <= 0) return false
    if (selected == NeedsReviewFilter.Duplicate) return false
    if (selected != NeedsReviewFilter.All) return true
    return !counts.hasSingleCompleteSignal
}

@Composable
internal fun InboxSectionNavigation(
    selected: InboxSection,
    onSelect: (InboxSection) -> Unit,
) {
    AppCompactChips {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        ) {
            InboxSection.entries.forEach { section ->
                AppFilterChip(
                    label = stringResource(section.labelRes),
                    selected = section == selected,
                    onClick = { onSelect(section) },
                )
            }
        }
    }
}

internal fun applyNeedsReviewFilter(items: List<Expense>, filter: NeedsReviewFilter): List<Expense> {
    return when (filter) {
        NeedsReviewFilter.All -> items
        NeedsReviewFilter.NeedsAmount -> items.filter { it.amountCents == null }
        NeedsReviewFilter.NeedsMerchant -> items.filter { pendingMerchantPresentation(it).needsReview }
        NeedsReviewFilter.NeedsCategory -> items.filter(::pendingNeedsCategory)
        NeedsReviewFilter.Duplicate -> items.filter { it.duplicateStatus == DuplicateStatusValues.SUSPECTED }
        NeedsReviewFilter.ReadyToConfirm -> items.filter {
            pendingPrimaryReviewAction(it) == PendingPrimaryReviewAction.Confirm
        }
    }
}

@Composable
internal fun NeedsReviewFilterBar(
    state: NeedsReviewFilterBarState,
    onSelect: (NeedsReviewFilter) -> Unit,
) {
    AppCompactChips {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        ) {
            visibleNeedsReviewFilters(state.counts, state.selected).forEach { f ->
                AppFilterChip(
                    label = stringResource(
                        R.string.pending_filter_chip_label,
                        stringResource(f.labelRes),
                        state.counts.countFor(f),
                    ),
                    selected = f == state.selected,
                    onClick = { onSelect(f) },
                )
            }
        }
    }
}

internal data class NeedsReviewFilterBarState(
    val selected: NeedsReviewFilter,
    val counts: PendingQueueCounts,
)

private fun PendingQueueCounts.countFor(filter: NeedsReviewFilter): Int = when (filter) {
    NeedsReviewFilter.All -> all
    NeedsReviewFilter.NeedsAmount -> needsAmount
    NeedsReviewFilter.NeedsMerchant -> needsMerchant
    NeedsReviewFilter.NeedsCategory -> needsCategory
    NeedsReviewFilter.Duplicate -> duplicate
    NeedsReviewFilter.ReadyToConfirm -> readyToConfirm
}

private val PendingQueueCounts.hasSingleCompleteSignal: Boolean
    get() {
        val total = all.coerceAtLeast(0)
        val visibleSignalCount = pendingSignalFilters.count { countFor(it) > 0 }
        return visibleSignalCount == 0 ||
            visibleSignalCount == 1 && pendingSignalFilters.any { countFor(it) == total }
    }

private val pendingSignalFilters = listOf(
    NeedsReviewFilter.NeedsAmount,
    NeedsReviewFilter.NeedsMerchant,
    NeedsReviewFilter.NeedsCategory,
    NeedsReviewFilter.ReadyToConfirm,
)

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
