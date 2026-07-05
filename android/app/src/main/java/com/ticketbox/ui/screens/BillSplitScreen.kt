package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.isInviteLocallyExpired
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppAdaptiveTrailingActionRow
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.BillSplitTargetLedger
import com.ticketbox.viewmodel.BillSplitViewModel

/**
 * ADR-0029 bill split UI: two tabs (Inbox / Sent), actions per row.
 *
 * v0.11 UI/UX P1 (structure): rendered on the shared page skeleton
 * ([AppSecondaryScrollableContent]) like RecurringScreen — an in-content secondary header,
 * chip tabs with counts, and one card per list with
 * divider-separated rows plus a shimmer loading state (previously the bare
 * Material `Scaffold`/`TopAppBar` showed nothing while loading). Data, actions,
 * navigation and copy are unchanged; only the layout moves onto the design system.
 */
@Composable
fun BillSplitScreen(
    viewModel: BillSplitViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var selectedTab by rememberSaveable { mutableStateOf(0) }
    val hasReadableData = state.inbox.isNotEmpty() || state.sent.isNotEmpty()

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = stringResource(R.string.bill_split_topbar_title),
            subtitle = null,
            backText = stringResource(R.string.bill_split_topbar_back),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.loading,
                hasReadableData = hasReadableData,
            ),
            onRefresh = viewModel::refresh,
        ),
    ) {
        item {
            BillSplitTabRow(
                selectedTab = selectedTab,
                onSelect = { selectedTab = it },
                inboxCount = state.inbox.size,
                sentCount = state.sent.size,
            )
        }
        state.message?.let {
            item {
                AppStatusBanner(message = it, tone = MessageTone.Danger)
            }
        }
        item {
            if (selectedTab == 0) {
                InboxCard(
                    inbox = state.inbox,
                    loading = state.loading && !hasReadableData,
                    onAccept = viewModel::accept,
                    onReject = viewModel::reject,
                    candidates = state.candidateTargetLedgers,
                )
            } else {
                SentCard(
                    sent = state.sent,
                    loading = state.loading && !hasReadableData,
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
        AppFilterChip(
            selected = selectedTab == 0,
            onClick = { onSelect(0) },
            label = stringResource(R.string.bill_split_tab_inbox, inboxCount),
        )
        AppFilterChip(
            selected = selectedTab == 1,
            onClick = { onSelect(1) },
            label = stringResource(R.string.bill_split_tab_sent, sentCount),
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
    AppGlassCard(containerAlpha = 0.94f) {
        AppListStateContent(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            state = AppListStateSpec(
                isEmpty = inbox.isEmpty(),
                loading = loading,
                emptyText = stringResource(R.string.bill_split_inbox_empty),
            ),
        ) {
            inbox.forEachIndexed { index, row ->
                if (index > 0) {
                    HorizontalDivider(color = LocalThemeVisuals.current.chipUnselected.copy(alpha = 0.72f))
                }
                InboxRow(
                    row = row,
                    onAccept = onAccept,
                    onReject = onReject,
                    candidates = candidates,
                )
            }
        }
    }
}

@Composable
private fun SentCard(
    sent: List<BillSplitSent>,
    loading: Boolean,
    onCancel: (String) -> Unit,
) {
    AppGlassCard(containerAlpha = 0.94f) {
        AppListStateContent(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            state = AppListStateSpec(
                isEmpty = sent.isEmpty(),
                loading = loading,
                emptyText = stringResource(R.string.bill_split_sent_empty),
            ),
        ) {
            sent.forEachIndexed { index, row ->
                if (index > 0) {
                    HorizontalDivider(color = LocalThemeVisuals.current.chipUnselected.copy(alpha = 0.72f))
                }
                SentRow(row = row, onCancel = onCancel)
            }
        }
    }
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
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        BillSplitPartyAmountRow(name = row.senderDisplayName, amountCents = row.amountCents)
        InboxMetaLine(row = row, locallyExpired = locallyExpired)
        if (row.status == BillSplitStatusValues.INVITED && !locallyExpired) {
            BillSplitInboxActions(
                row = row,
                candidates = candidates,
                onAccept = onAccept,
                onReject = onReject,
            )
        }
    }
}

@Composable
private fun BillSplitInboxActions(
    row: BillSplitInbox,
    candidates: List<BillSplitTargetLedger>,
    onAccept: (String, String) -> Unit,
    onReject: (String) -> Unit,
) {
    val hasAcceptAction = candidates.isNotEmpty()
    val actionCount = if (hasAcceptAction) 2 else 1
    val acceptAction: @Composable (Modifier) -> Unit = { actionModifier ->
        // Audit P3 #3: show the ledger NAME (the button used to print the internal ledger_id),
        // and let a multi-ledger member PICK the target instead of hard-wiring the first writable one.
        when {
            candidates.isEmpty() -> Unit
            candidates.size == 1 -> OutlinedButton(
                modifier = actionModifier,
                onClick = { onAccept(row.publicId, candidates.single().ledgerId) },
            ) {
                Text(stringResource(R.string.bill_split_inbox_accept, candidates.single().name))
            }
            else -> AcceptTargetPicker(
                modifier = actionModifier,
                buttonModifier = actionModifier,
                publicId = row.publicId,
                candidates = candidates,
                onAccept = onAccept,
            )
        }
    }
    AppAdaptiveEditActionLayout(
        actionCount = actionCount,
        compact = false,
        stackTwoActionsOnNarrow = hasAcceptAction,
    ) { mode ->
        when (mode) {
            AppAdaptiveEditActionMode.Stacked -> Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                acceptAction(Modifier.fillMaxWidth())
                OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = { onReject(row.publicId) }) {
                    Text(stringResource(R.string.bill_split_inbox_reject))
                }
            }
            AppAdaptiveEditActionMode.Compact,
            AppAdaptiveEditActionMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End),
            ) {
                acceptAction(Modifier)
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
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        BillSplitPartyAmountRow(name = row.receiverDisplayNameSnapshot ?: "—", amountCents = row.amountCents)
        Text(
            text = "${row.merchantSnapshot ?: "—"} · ${billSplitStatusLabel(row.status)}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        if (row.status == BillSplitStatusValues.INVITED) {
            AppAdaptiveTrailingActionRow {
                OutlinedButton(modifier = it, onClick = { onCancel(row.publicId) }) {
                    Text(stringResource(R.string.bill_split_sent_cancel))
                }
            }
        }
    }
}

@Composable
private fun BillSplitPartyAmountRow(
    name: String,
    amountCents: Long,
) {
    AppAdaptiveContentActionRow(
        modifier = Modifier.fillMaxWidth(),
        wideActionWeight = BillSplitAmountWideWeight,
        content = {
            Text(
                text = name,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        },
        action = { actionModifier ->
            AppEndAlignedAmountText(
                text = formatAmount(amountCents),
                modifier = actionModifier,
                role = AppAmountRole.Compact,
            )
        },
    )
}

@Composable
private fun AcceptTargetPicker(
    modifier: Modifier = Modifier,
    buttonModifier: Modifier = Modifier,
    publicId: String,
    candidates: List<BillSplitTargetLedger>,
    onAccept: (String, String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier = modifier) {
        OutlinedButton(modifier = buttonModifier, onClick = { expanded = true }) {
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

private const val BillSplitAmountWideWeight = 0.54f
