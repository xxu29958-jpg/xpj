package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
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
import com.ticketbox.domain.model.ExpenseAccountingTime
import com.ticketbox.domain.model.isInviteLocallyExpired
import com.ticketbox.domain.model.presentedStatus
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
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
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.accountingTimeDateText
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.asString
import com.ticketbox.viewmodel.BillSplitViewModel

data class BillSplitNavigation(
    val openBill: (LogicalSessionBinding, Long, String) -> Unit,
    val busy: Boolean = false,
    val error: UiText? = null,
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun BillSplitScreen(
    viewModel: BillSplitViewModel,
    onBack: () -> Unit,
    navigation: BillSplitNavigation,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var selectedTab by rememberSaveable { mutableStateOf(0) }
    val hasReadableData = state.inboxEntryCount > 0 || state.sent.isNotEmpty()
    val bodyStates = billSplitScreenBodyStates(state = state, selectedTab = selectedTab)
    val acceptance = BillSplitAcceptanceControls(state.selectedTargets, state.acceptances.mapNotNull { it.payload?.publicId }.toSet(),
        state.candidateTargetLedgers, select = { id, target -> state.access?.binding?.let { viewModel.selectTarget(it, id, target) } },
        accept = { id, target -> state.access?.binding?.let { viewModel.accept(it, id, target) } })

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
            BillSplitTabs(state.inboxEntryCount, state.sent.size, selectedTab) { selectedTab = it }
        }
        state.message?.takeIf { bodyStates.selected != ReadableListBodyState.LoadFailed }?.let {
            item {
                AppStatusBanner(message = it, tone = state.messageTone)
            }
        }
        navigation.error?.let { item { AppStatusBanner(message = it, tone = MessageTone.Danger) } }
        if (selectedTab == 0) billSplitAcceptanceTasks(state, viewModel, navigation, acceptance)
        item {
            if (selectedTab == 0) {
                InboxCard(
                    inbox = state.inbox.filterNot { row -> row.status != BillSplitStatusValues.ACCEPTED &&
                        state.acceptances.any { it.delivered && it.payload?.publicId == row.publicId } },
                    chrome = BillSplitListChrome(bodyStates.inbox, viewModel::refresh, state.access, navigation, !state.loading && !navigation.busy),
                    acceptance = acceptance,
                    showEmpty = state.inboxEntryCount == 0,
                    onReject = { id -> state.access?.binding?.let { viewModel.reject(it, id) } },
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

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun BillSplitTabs(inboxCount: Int, sentCount: Int, selected: Int, select: (Int) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppFilterChip(selected = selected == 0, onClick = { select(0) },
            label = stringResource(R.string.bill_split_tab_inbox, inboxCount))
        AppFilterChip(selected = selected == 1, onClick = { select(1) },
            label = stringResource(R.string.bill_split_tab_sent, sentCount))
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
    acceptance: BillSplitAcceptanceControls,
    showEmpty: Boolean,
    onReject: (String) -> Unit,
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
        ReadableListBodyState.Content -> if (inbox.isNotEmpty() || showEmpty) AppPaperCard {
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
                        acceptance = acceptance,
                        onReject = onReject,
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
    acceptance: BillSplitAcceptanceControls,
    onReject: (String) -> Unit,
    chrome: BillSplitListChrome,
) {
    // Between expires_at and the server sweep the row is still status=invited;
    // derive 已过期 locally (like /web's inbox is_expired) so the buttons hide
    // instead of inviting a tap that can only 410.
    val locallyExpired = row.isInviteLocallyExpired()
    val statusLabel = billSplitStatusLabel(if (locallyExpired) BillSplitStatusValues.EXPIRED else row.status)
    val warnColor = LocalStateTokens.current.warn.fg
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        BillSplitPartyAmountRow(name = row.senderDisplayName, amountCents = row.amountCents, currencyCode = row.homeCurrencyCode)
        Text(text = buildAnnotatedString {
            append("${row.merchantSnapshot ?: "—"} · ${row.categorySuggestion ?: "—"} · ")
            if (locallyExpired) withStyle(SpanStyle(color = warnColor)) { append(statusLabel) }
            else append(statusLabel)
        }, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        BillSplitSourceEvidence(row.originalAmountMinor, row.originalCurrencyCode,
            row.accountingTimeSnapshot, row.expenseTimeSnapshot)
        BillSplitTimeline(row.createdAt, row.acceptedAt, row.rejectedAt, row.cancelledAt, row.expiredAt)
        Text(stringResource(if (row.status == BillSplitStatusValues.INVITED) R.string.bill_split_deadline
            else R.string.bill_split_original_deadline, displayDateTime(row.expiresAt)),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        row.receivedBill?.let { received ->
            Text(stringResource(R.string.bill_split_received_ledger, received.ledgerName),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            AppSecondaryButton(text = stringResource(R.string.bill_split_open_received), enabled = chrome.actionsEnabled,
                onClick = { chrome.access?.binding?.let { chrome.navigation.openBill(it, received.expenseId, received.ledgerId) } })
        }
        if (row.status == BillSplitStatusValues.INVITED && !locallyExpired) {
            BillSplitInboxActions(
                row = row,
                acceptance = acceptance,
                onReject = onReject,
                enabled = chrome.actionsEnabled,
            )
        }
    }
}

@Composable
private fun BillSplitInboxActions(row: BillSplitInbox, acceptance: BillSplitAcceptanceControls,
                                  onReject: (String) -> Unit, enabled: Boolean) {
    if (row.publicId in acceptance.pendingIds) return
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        BillSplitAcceptancePicker(row.publicId, acceptance, enabled)
        AppSecondaryButton(text = stringResource(R.string.bill_split_inbox_reject), enabled = enabled,
            onClick = { onReject(row.publicId) })
    }
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
        if (row.currentAgreedShareAmountCents != row.amountCents) {
            Text(stringResource(R.string.bill_split_current_share, "${row.homeCurrencyCode} " +
                formatDisplayAmount(row.currentAgreedShareAmountCents, CurrencyDisplay.forRecord(row.homeCurrencyCode))),
                style = MaterialTheme.typography.bodyMedium)
        }
        BillSplitSourceEvidence(row.originalAmountMinor, row.originalCurrencyCode,
            row.accountingTimeSnapshot, row.expenseTimeSnapshot)
        BillSplitTimeline(row.createdAt, row.acceptedAt, row.rejectedAt, row.cancelledAt, row.expiredAt)
        Text(stringResource(if (presented == BillSplitStatusValues.INVITED) R.string.bill_split_deadline
            else R.string.bill_split_original_deadline, displayDateTime(row.expiresAt)),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
        AppSecondaryButton(text = stringResource(R.string.bill_split_open_source), enabled = chrome.actionsEnabled,
            onClick = { chrome.access?.binding?.let { chrome.navigation.openBill(it, row.senderExpenseId, it.ledgerId) } })
        if (presented == BillSplitStatusValues.INVITED && chrome.access?.canModify == true) {
            AppAdaptiveTrailingActionRow {
                AppSecondaryButton(
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
    Text(stringResource(R.string.bill_split_invitation_share, currencyCode),
        style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    AppAdaptiveContentActionRow(
        modifier = Modifier.fillMaxWidth(),
        style = AppAdaptiveContentActionStyle(wideActionWeight = BillSplitAmountWideWeight),
        content = {
            Text(
                text = name,
                fontWeight = FontWeight.SemiBold,
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
private fun BillSplitSourceEvidence(amount: Long?, currency: String?, time: ExpenseAccountingTime?, legacyTime: String?) {
    val label = if (amount != null && currency != null) stringResource(R.string.bill_split_source_amount,
        "$currency ${formatDisplayAmount(amount, CurrencyDisplay.forRecord(currency))}")
        else stringResource(R.string.bill_split_source_amount_unknown)
    Text(label, style = MaterialTheme.typography.bodyMedium)
    Text(stringResource(R.string.bill_split_source_date, accountingTimeDateText(time, legacyTime).asString()),
        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun BillSplitTimeline(created: String, accepted: String?, rejected: String?, cancelled: String?, expired: String?) {
    listOf(R.string.bill_split_created to created, R.string.bill_split_status_accepted to accepted,
        R.string.bill_split_status_rejected to rejected, R.string.bill_split_status_cancelled to cancelled,
        R.string.bill_split_expiry_recorded to expired).forEach { (label, time) ->
        if (time != null) Text(stringResource(R.string.bill_split_event_time, stringResource(label), displayDateTime(time)),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
