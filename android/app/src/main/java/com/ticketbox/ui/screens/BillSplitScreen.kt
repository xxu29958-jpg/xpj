package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.BillSplitViewModel
import com.valentinilk.shimmer.shimmer

/**
 * ADR-0029 bill split UI: two tabs (Inbox / Sent), actions per row.
 *
 * v0.11 UI/UX P1 (structure): rendered on the shared page skeleton
 * ([AppScrollableContent]) like RecurringScreen — an in-content back button +
 * [AppPageHeader], chip tabs with counts, and one card per list with
 * divider-separated rows plus a shimmer loading state (previously the bare
 * Material `Scaffold`/`TopAppBar` showed nothing while loading). Data, actions,
 * navigation and copy are unchanged; only the layout moves onto the design system.
 */
@Composable
fun BillSplitScreen(
    viewModel: BillSplitViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsState()
    var selectedTab by rememberSaveable { mutableStateOf(0) }

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.loading,
        onRefresh = viewModel::refresh,
        hasBottomBar = false,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                TextButton(onClick = onBack) {
                    Icon(
                        Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = stringResource(R.string.bill_split_topbar_back),
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                    Text(stringResource(R.string.bill_split_topbar_back))
                }
                AppPageHeader(title = stringResource(R.string.bill_split_topbar_title))
                BillSplitTabRow(
                    selectedTab = selectedTab,
                    onSelect = { selectedTab = it },
                    inboxCount = state.inbox.size,
                    sentCount = state.sent.size,
                )
            }
        }
        state.message?.let {
            item {
                Text(it.asString(), color = MaterialTheme.colorScheme.error)
            }
        }
        item {
            if (selectedTab == 0) {
                InboxCard(
                    inbox = state.inbox,
                    loading = state.loading,
                    onAccept = viewModel::accept,
                    onReject = viewModel::reject,
                    candidateTargetLedgerIds = state.candidateTargetLedgerIds,
                )
            } else {
                SentCard(
                    sent = state.sent,
                    loading = state.loading,
                    onCancel = viewModel::cancel,
                )
            }
        }
    }
}

@Composable
private fun BillSplitTabRow(
    selectedTab: Int,
    onSelect: (Int) -> Unit,
    inboxCount: Int,
    sentCount: Int,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        FilterChip(
            selected = selectedTab == 0,
            onClick = { onSelect(0) },
            label = { Text(stringResource(R.string.bill_split_tab_inbox, inboxCount)) },
        )
        FilterChip(
            selected = selectedTab == 1,
            onClick = { onSelect(1) },
            label = { Text(stringResource(R.string.bill_split_tab_sent, sentCount)) },
        )
    }
}

@Composable
private fun InboxCard(
    inbox: List<BillSplitInbox>,
    loading: Boolean,
    onAccept: (String, String) -> Unit,
    onReject: (String) -> Unit,
    candidateTargetLedgerIds: List<String>,
) {
    BillSplitListCard(isEmpty = inbox.isEmpty(), loading = loading, emptyRes = R.string.bill_split_inbox_empty) {
        inbox.forEachIndexed { index, row ->
            if (index > 0) RowDivider()
            InboxRow(
                row = row,
                onAccept = onAccept,
                onReject = onReject,
                candidateTargetLedgerIds = candidateTargetLedgerIds,
            )
        }
    }
}

@Composable
private fun SentCard(
    sent: List<BillSplitSent>,
    loading: Boolean,
    onCancel: (String) -> Unit,
) {
    BillSplitListCard(isEmpty = sent.isEmpty(), loading = loading, emptyRes = R.string.bill_split_sent_empty) {
        sent.forEachIndexed { index, row ->
            if (index > 0) RowDivider()
            SentRow(row = row, onCancel = onCancel)
        }
    }
}

/** One card holding a list: shimmer skeleton while loading-empty, an empty line
 *  when settled-empty, else the divider-separated [rows]. Mirrors RecurringItemsCard. */
@Composable
private fun BillSplitListCard(
    isEmpty: Boolean,
    loading: Boolean,
    @StringRes emptyRes: Int,
    rows: @Composable ColumnScope.() -> Unit,
) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            when {
                isEmpty && loading -> Column(modifier = Modifier.shimmer()) {
                    repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
                }
                isEmpty -> Text(
                    text = stringResource(emptyRes),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                else -> rows()
            }
        }
    }
}

@Composable
private fun RowDivider() {
    val visuals = LocalThemeVisuals.current
    HorizontalDivider(color = visuals.chipUnselected.copy(alpha = 0.72f))
}

@Composable
private fun InboxRow(
    row: BillSplitInbox,
    onAccept: (String, String) -> Unit,
    onReject: (String) -> Unit,
    candidateTargetLedgerIds: List<String>,
) {
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(row.senderDisplayName, fontWeight = FontWeight.SemiBold)
            Text(formatAmount(row.amountCents))
        }
        Text(
            text = "${row.merchantSnapshot ?: "—"} · ${row.categorySuggestion ?: "—"} · ${row.status}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        if (row.status == BillSplitStatusValues.INVITED) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                candidateTargetLedgerIds.firstOrNull()?.let { firstLedger ->
                    OutlinedButton(onClick = { onAccept(row.publicId, firstLedger) }) {
                        Text(stringResource(R.string.bill_split_inbox_accept, firstLedger))
                    }
                }
                OutlinedButton(onClick = { onReject(row.publicId) }) {
                    Text(stringResource(R.string.bill_split_inbox_reject))
                }
            }
        }
    }
}

@Composable
private fun SentRow(
    row: BillSplitSent,
    onCancel: (String) -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(row.receiverDisplayNameSnapshot ?: "—", fontWeight = FontWeight.SemiBold)
            Text(formatAmount(row.amountCents))
        }
        Text(
            text = "${row.merchantSnapshot ?: "—"} · ${row.status}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        if (row.status == BillSplitStatusValues.INVITED) {
            OutlinedButton(onClick = { onCancel(row.publicId) }) {
                Text(stringResource(R.string.bill_split_sent_cancel))
            }
        }
    }
}
