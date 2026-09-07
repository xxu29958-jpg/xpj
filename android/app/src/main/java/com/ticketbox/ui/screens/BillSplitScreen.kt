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
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.isInviteLocallyExpired
import com.ticketbox.domain.model.presentedStatus
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveTrailingActionRow
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.BillSplitTargetLedger
import com.ticketbox.viewmodel.BillSplitViewModel

data class BillSplitNavigation(
    val openBill: (LogicalSessionBinding, Long, String) -> Unit,
    val busy: Boolean = false,
    val error: UiText? = null,
)

@Composable
fun BillSplitScreen(
    viewModel: BillSplitViewModel,
    onBack: () -> Unit,
    navigation: BillSplitNavigation,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var selectedTab by rememberSaveable { mutableStateOf(0) }
    val hasReadableData = state.inbox.isNotEmpty() || state.sent.isNotEmpty()
    val bodyStates = billSplitScreenBodyStates(state = state, selectedTab = selectedTab)

    LaunchedEffect(state.access?.binding) {
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
        state.message?.takeIf { bodyStates.selected != ReadableListBodyState.LoadFailed }?.let {
            item {
                AppStatusBanner(message = it, tone = state.messageTone)
            }
        }
        navigation.error?.let { item { AppStatusBanner(message = it, tone = MessageTone.Danger) } }
        item {
            if (selectedTab == 0) {
                InboxCard(
                    inbox = state.inbox,
                    chrome = BillSplitListChrome(bodyStates.inbox, viewModel::refresh, state.access, navigation, !state.loading && !navigation.busy),
                    onAccept = { id, target -> state.access?.binding?.let { viewModel.accept(it, id, target) } },
                    onReject = { id -> state.access?.binding?.let { viewModel.reject(it, id) } },
                    candidates = state.candidateTargetLedgers,
                )
            } else {
                SentCard(
                    sent = state.sent,
                    chrome = BillSplitListChrome(bodyStates.sent, viewModel::refresh, state.access, navigation, !state.loading && !navigation.busy),
                    onCancel = { id -> state.access?.binding?.let { viewModel.cancel(it, id) } },
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

private data class BillSplitListChrome(
    val bodyState: ReadableListBodyState,
    val onRetry: () -> Unit,
    val access: LedgerAccessContext?,
    val navigation: BillSplitNavigation,
    val actionsEnabled: Boolean,
)

@Composable
private fun InboxCard(
    inbox: List<BillSplitInbox>,
    chrome: BillSplitListChrome,
    onAccept: (String, String) -> Unit,
    onReject: (String) -> Unit,
    candidates: List<BillSplitTargetLedger>,
) {
    when (chrome.bodyState) {
        ReadableListBodyState.Loading -> BillSplitLoadingState(
            title = stringResource(R.string.bill_split_inbox_loading_title),
            body = stringResource(R.string.bill_split_inbox_loading_body),
            emptyText = stringResource(R.string.bill_split_inbox_empty),
        )
        ReadableListBodyState.LoadFailed -> AppErrorState(
            title = stringResource(R.string.bill_split_inbox_load_failed_title),
            body = stringResource(R.string.bill_split_inbox_load_failed_body),
            onRetry = chrome.onRetry,
        )
        ReadableListBodyState.Empty,
        ReadableListBodyState.Content -> AppPaperCard {
            AppListStateContent(
                modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
                state = AppListStateSpec(
                    isEmpty = inbox.isEmpty(),
                    loading = false,
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
                        chrome = chrome,
                    )
                }
            }
        }
    }
}

@Composable
private fun SentCard(
    sent: List<BillSplitSent>,
    chrome: BillSplitListChrome,
    onCancel: (String) -> Unit,
) {
    when (chrome.bodyState) {
        ReadableListBodyState.Loading -> BillSplitLoadingState(
            title = stringResource(R.string.bill_split_sent_loading_title),
            body = stringResource(R.string.bill_split_sent_loading_body),
            emptyText = stringResource(R.string.bill_split_sent_empty),
        )
        ReadableListBodyState.LoadFailed -> AppErrorState(
            title = stringResource(R.string.bill_split_sent_load_failed_title),
            body = stringResource(R.string.bill_split_sent_load_failed_body),
            onRetry = chrome.onRetry,
        )
        ReadableListBodyState.Empty,
        ReadableListBodyState.Content -> AppPaperCard {
            AppListStateContent(
                modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
                state = AppListStateSpec(
                    isEmpty = sent.isEmpty(),
                    loading = false,
                    emptyText = stringResource(R.string.bill_split_sent_empty),
                ),
            ) {
                sent.forEachIndexed { index, row ->
                    if (index > 0) {
                        HorizontalDivider(color = LocalThemeVisuals.current.chipUnselected.copy(alpha = 0.72f))
                    }
                    SentRow(row = row, onCancel = onCancel, chrome = chrome)
                }
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
    chrome: BillSplitListChrome,
) {
    // Between expires_at and the server sweep the row is still status=invited;
    // derive 已过期 locally (like /web's inbox is_expired) so the buttons hide
    // instead of inviting a tap that can only 410.
    val locallyExpired = row.isInviteLocallyExpired()
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        BillSplitPartyAmountRow(name = row.senderDisplayName, amountCents = row.amountCents, currencyCode = row.homeCurrencyCode)
        InboxMetaLine(row = row, locallyExpired = locallyExpired)
        row.receivedBill?.let { received ->
            Text(stringResource(R.string.bill_split_received_ledger, received.ledgerName),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            QuietOutlinedButton(text = stringResource(R.string.bill_split_open_received), enabled = chrome.actionsEnabled,
                onClick = { chrome.access?.binding?.let { chrome.navigation.openBill(it, received.expenseId, received.ledgerId) } })
        }
        if (row.status == BillSplitStatusValues.INVITED && !locallyExpired) {
            BillSplitInboxActions(
                row = row,
                candidates = candidates,
                onAccept = onAccept,
                onReject = onReject,
                enabled = chrome.actionsEnabled,
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
    enabled: Boolean,
) {
    val hasAcceptAction = candidates.isNotEmpty()
    val actionCount = if (hasAcceptAction) 2 else 1
    val acceptAction: @Composable (Modifier) -> Unit = { actionModifier ->
        // Audit P3 #3: show the ledger NAME (the button used to print the internal ledger_id),
        // and let a multi-ledger member PICK the target instead of hard-wiring the first writable one.
        when {
            candidates.isEmpty() -> Unit
            candidates.size == 1 -> QuietOutlinedButton(
                text = stringResource(R.string.bill_split_inbox_accept, candidates.single().name),
                modifier = actionModifier,
                enabled = enabled,
                onClick = { onAccept(row.publicId, candidates.single().ledgerId) },
            )
            else -> AcceptTargetPicker(
                modifier = actionModifier,
                enabled = enabled,
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
                QuietOutlinedButton(
                    text = stringResource(R.string.bill_split_inbox_reject),
                    enabled = enabled,
                    modifier = Modifier.fillMaxWidth(),
                    onClick = { onReject(row.publicId) },
                )
            }
            AppAdaptiveEditActionMode.Compact,
            AppAdaptiveEditActionMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End),
            ) {
                acceptAction(Modifier)
                QuietOutlinedButton(
                    text = stringResource(R.string.bill_split_inbox_reject),
                    enabled = enabled,
                    onClick = { onReject(row.publicId) },
                )
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
    chrome: BillSplitListChrome,
) {
    // Share the local expiry mirror with the expense fact page; the server
    // command remains authoritative.
    val presented = row.presentedStatus()
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        BillSplitPartyAmountRow(name = row.receiverDisplayNameSnapshot ?: "—", amountCents = row.amountCents, currencyCode = row.homeCurrencyCode)
        val statusLabel = billSplitStatusLabel(presented)
        val warnColor = LocalStateTokens.current.warn.fg
        Text(
            text = buildAnnotatedString {
                append("${row.merchantSnapshot ?: "—"} · ")
                if (presented == BillSplitStatusValues.EXPIRED) {
                    withStyle(SpanStyle(color = warnColor)) { append(statusLabel) }
                } else {
                    append(statusLabel)
                }
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        QuietOutlinedButton(text = stringResource(R.string.bill_split_open_source), enabled = chrome.actionsEnabled,
            onClick = { chrome.access?.binding?.let { chrome.navigation.openBill(it, row.senderExpenseId, it.ledgerId) } })
        if (presented == BillSplitStatusValues.INVITED && chrome.access?.canModify == true) {
            AppAdaptiveTrailingActionRow {
                QuietOutlinedButton(
                    text = stringResource(R.string.bill_split_sent_cancel),
                    modifier = it,
                    enabled = chrome.actionsEnabled,
                    onClick = { onCancel(row.publicId) },
                )
            }
        }
    }
}

@Composable
private fun BillSplitPartyAmountRow(
    name: String,
    amountCents: Long,
    currencyCode: String,
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
                text = formatDisplayAmount(amountCents, CurrencyDisplay.forRecord(currencyCode)),
                modifier = actionModifier,
                role = AppAmountRole.Compact,
            )
        },
    )
}

@Composable
private fun AcceptTargetPicker(
    modifier: Modifier = Modifier,
    enabled: Boolean,
    publicId: String,
    candidates: List<BillSplitTargetLedger>,
    onAccept: (String, String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier = modifier) {
        QuietOutlinedButton(
            text = stringResource(R.string.bill_split_accept_picker_title),
            modifier = Modifier.fillMaxWidth(),
            enabled = enabled,
            onClick = { expanded = true },
        )
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
