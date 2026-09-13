package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.ReceiptEmptyIllustration
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.screens.LedgerRecordCtaSlot
import com.ticketbox.viewmodel.LedgerUiState

/**
 * W2-B 流水空态：单一 CTA 纪律（承 W2-A pending 空态）——
 * 有筛选的唯一动作是「重置筛选」（含 Viewer，清筛选是读侧动作）；
 * 无筛选的 writer 空态唯一动作是「记一笔」（页头不再重复渲染）；
 * Viewer 无任何写入口。刷新能力由下拉刷新 + 头部新鲜度行 + 工具内同步承担，
 * 不再有常驻「更新账本」按钮。
 */
@Composable
private fun ledgerEmptyTitle(state: LedgerUiState): String {
    val hasMonth = state.monthFilter.isNotBlank()
    val hasCategory = state.categoryFilter.isNotBlank()
    val hasTag = state.tagFilter.isNotBlank()
    return when {
        hasTag -> stringResource(R.string.ledger_empty_title_tag, state.tagFilter)
        hasMonth && hasCategory -> stringResource(
            R.string.ledger_empty_title_month_category,
            displayMonthLabel(state.monthFilter),
            state.categoryFilter,
        )
        hasMonth -> stringResource(R.string.ledger_empty_title_month, displayMonthLabel(state.monthFilter))
        hasCategory -> stringResource(R.string.ledger_empty_title_category, state.categoryFilter)
        else -> stringResource(R.string.ledger_empty_title_default)
    }
}

@Composable
private fun ledgerEmptyBody(state: LedgerUiState): String {
    val hasScopedFilter = state.monthFilter.isNotBlank() ||
        state.categoryFilter.isNotBlank() ||
        state.tagFilter.isNotBlank()
    return when {
        hasScopedFilter -> stringResource(R.string.ledger_empty_body_filtered)
        state.readOnly -> stringResource(R.string.ledger_empty_body_readonly)
        else -> stringResource(R.string.ledger_empty_body_default)
    }
}

@Composable
private fun LedgerEmptyCta(
    state: LedgerUiState,
    recordCtaSlot: LedgerRecordCtaSlot?,
    onClearFilters: () -> Unit,
    onManualAdd: () -> Unit,
) {
    when {
        state.filter.hasFilters -> {
            AppOutlinedButton(
                modifier = Modifier.fillMaxWidth(),
                onClick = onClearFilters,
                options = AppOutlinedButtonOptions(),
            ) {
                Text(stringResource(R.string.ledger_empty_reset_filters))
            }
        }
        recordCtaSlot == LedgerRecordCtaSlot.EmptyState -> {
            AppPrimaryButton(
                text = stringResource(R.string.ledger_header_add_button),
                icon = Icons.Filled.Add,
                modifier = Modifier.fillMaxWidth(),
                onClick = onManualAdd,
            )
        }
    }
}

@Composable
internal fun EmptyLedgerState(
    state: LedgerUiState,
    recordCtaSlot: LedgerRecordCtaSlot?,
    onClearFilters: () -> Unit,
    onManualAdd: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(
                top = AppSpacing.compactGap,
                bottom = AppSpacing.bottomContentPadding,
            ),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // An unfiltered empty task may show receipt art; a filter miss stays operational.
        if (recordCtaSlot == LedgerRecordCtaSlot.EmptyState) {
            ReceiptEmptyIllustration(
                modifier = Modifier.padding(bottom = AppSpacing.miniGap),
            )
        }
        Text(
            text = ledgerEmptyTitle(state),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            textAlign = TextAlign.Center,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = ledgerEmptyBody(state),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        LedgerEmptyCta(
            state = state,
            recordCtaSlot = recordCtaSlot,
            onClearFilters = onClearFilters,
            onManualAdd = onManualAdd,
        )
    }
}

/**
 * 8.4: chooses between the first-sync skeleton and the genuine empty state.
 * Extracted from LedgerScreen's ``item {}`` so that screen's lambda body stays
 * shallow (NestedBlockDepth gate) — the branch + skeleton blocks live here.
 */
@Composable
internal fun LedgerEmptyOrFirstSync(
    state: LedgerUiState,
    recordCtaSlot: LedgerRecordCtaSlot?,
    onClearFilters: () -> Unit,
    onManualAdd: () -> Unit,
) {
    if (state.isFirstSync) {
        LedgerFirstSyncSkeleton()
    } else {
        EmptyLedgerState(
            state = state,
            recordCtaSlot = recordCtaSlot,
            onClearFilters = onClearFilters,
            onManualAdd = onManualAdd,
        )
    }
}

/** First-ever-sync placeholder list (shimmer skeleton rows). Mirrors PendingScreen. */
@Composable
private fun LedgerFirstSyncSkeleton() {
    AppListStateContent(
        state = AppListStateSpec(
            isEmpty = true,
            loading = true,
            emptyText = stringResource(R.string.ledger_empty_body_default),
            skeletonRows = 6,
        ),
    ) {}
}
