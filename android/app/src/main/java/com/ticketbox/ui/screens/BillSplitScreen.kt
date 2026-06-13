package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.isInviteLocallyExpired
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.BillSplitTargetLedger
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

    // 系统返回键交给 onBack(镜像 BudgetScreen/RecurringScreen)。本屏可作全屏二级页
    // 渲染——账本工具表入口走 statsSecondaryPage overlay、设置树入口走 SettingsDestinationHost——
    // overlay 路径下没有外层 BackHandler(NavHost 仍在 start destination、回退栈为空),
    // 缺这一句系统返回会穿透到 Activity 把 app 切后台而非回账本。
    BackHandler { onBack() }

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
                    candidates = state.candidateTargetLedgers,
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
    candidates: List<BillSplitTargetLedger>,
) {
    BillSplitListCard(isEmpty = inbox.isEmpty(), loading = loading, emptyRes = R.string.bill_split_inbox_empty) {
        inbox.forEachIndexed { index, row ->
            if (index > 0) RowDivider()
            InboxRow(
                row = row,
                onAccept = onAccept,
                onReject = onReject,
                candidates = candidates,
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
    candidates: List<BillSplitTargetLedger>,
) {
    // Between expires_at and the server sweep the row is still status=invited;
    // derive 已过期 locally (like /web's inbox is_expired) so the buttons hide
    // instead of inviting a tap that can only 410.
    val locallyExpired = row.isInviteLocallyExpired()
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(row.senderDisplayName, fontWeight = FontWeight.SemiBold)
            Text(formatAmount(row.amountCents), style = LocalTextStyle.current.tabularNum())
        }
        InboxMetaLine(row = row, locallyExpired = locallyExpired)
        if (row.status == BillSplitStatusValues.INVITED && !locallyExpired) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                // Audit P3 #3: show the ledger NAME (the button used to print
                // the internal ledger_id), and let a multi-ledger member PICK
                // the target instead of hard-wiring the first writable one.
                when {
                    candidates.isEmpty() -> Unit
                    candidates.size == 1 -> OutlinedButton(
                        onClick = { onAccept(row.publicId, candidates.single().ledgerId) },
                    ) {
                        Text(stringResource(R.string.bill_split_inbox_accept, candidates.single().name))
                    }
                    else -> AcceptTargetPicker(
                        publicId = row.publicId,
                        candidates = candidates,
                        onAccept = onAccept,
                    )
                }
                OutlinedButton(onClick = { onReject(row.publicId) }) {
                    Text(stringResource(R.string.bill_split_inbox_reject))
                }
            }
        }
    }
}

/** Meta line `商家 · 分类 · 状态`. A locally-expired invited row shows the
 *  已过期 label in the warn state tone (mirrors /web's warn pill); every other
 *  row keeps the plain server-status rendering. */
@Composable
private fun InboxMetaLine(row: BillSplitInbox, locallyExpired: Boolean) {
    val statusLabel = billSplitStatusLabel(
        if (locallyExpired) BillSplitStatusValues.EXPIRED else row.status,
    )
    val warnColor = LocalStateTokens.current.warn.fg
    Text(
        text = buildAnnotatedString {
            append("${row.merchantSnapshot ?: "—"} · ${row.categorySuggestion ?: "—"} · ")
            if (locallyExpired) {
                withStyle(SpanStyle(color = warnColor)) { append(statusLabel) }
            } else {
                append(statusLabel)
            }
        },
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
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
            Text(formatAmount(row.amountCents), style = LocalTextStyle.current.tabularNum())
        }
        Text(
            text = "${row.merchantSnapshot ?: "—"} · ${billSplitStatusLabel(row.status)}",
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

@Composable
private fun AcceptTargetPicker(
    publicId: String,
    candidates: List<BillSplitTargetLedger>,
    onAccept: (String, String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(onClick = { expanded = true }) {
            Text(stringResource(R.string.bill_split_accept_picker_title))
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            candidates.forEach { candidate ->
                DropdownMenuItem(
                    text = { Text(candidate.name) },
                    onClick = {
                        expanded = false
                        onAccept(publicId, candidate.ledgerId)
                    },
                )
            }
        }
    }
}

@Composable
private fun billSplitStatusLabel(status: String): String = stringResource(
    when (status) {
        BillSplitStatusValues.INVITED -> R.string.bill_split_status_invited
        BillSplitStatusValues.ACCEPTED -> R.string.bill_split_status_accepted
        BillSplitStatusValues.REJECTED -> R.string.bill_split_status_rejected
        BillSplitStatusValues.CANCELLED -> R.string.bill_split_status_cancelled
        else -> R.string.bill_split_status_expired
    },
)
