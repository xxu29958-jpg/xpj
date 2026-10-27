package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.BillSplitAcceptPayload
import com.ticketbox.data.repository.PendingBillSplitAcceptance
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.isInviteLocallyExpired
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.viewmodel.BillSplitViewModel
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.screens.settings.friendlyLastError
import com.ticketbox.viewmodel.BillSplitTargetLedger

internal data class BillSplitAcceptanceControls(
    val selections: Map<String, BillSplitAcceptPayload>,
    val pendingIds: Set<String>,
    val candidates: List<BillSplitTargetLedger>,
    val select: (String, String) -> Unit,
    val accept: (String, String) -> Unit,
)

@Composable
internal fun BillSplitAcceptancePicker(publicId: String, controls: BillSplitAcceptanceControls, enabled: Boolean) {
    val selected = controls.selections[publicId]
    val targetName = selected?.targetLedgerName ?: controls.candidates.singleOrNull()?.name
    var expanded by rememberSaveable(publicId) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (controls.candidates.isNotEmpty() || selected != null) {
            Box {
                AppSecondaryButton(text = targetName?.let { stringResource(R.string.bill_split_accept_selection, it) }
                    ?: stringResource(R.string.bill_split_accept_picker_title), enabled = enabled && controls.candidates.isNotEmpty(),
                    onClick = { expanded = true })
                DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    controls.candidates.forEach { candidate ->
                        DropdownMenuItem(text = { Text(candidate.name) }, onClick = {
                            expanded = false; controls.select(publicId, candidate.ledgerId)
                        })
                    }
                }
            }
        }
    }
}

@Composable
internal fun BillSplitInvitationSheet(row: BillSplitInbox, controls: BillSplitAcceptanceControls,
    enabled: Boolean, onReject: (String) -> Unit, onClose: () -> Unit) {
    val targetId = controls.selections[row.publicId]?.targetLedgerId ?: controls.candidates.singleOrNull()?.ledgerId
    AppBusyGuardedSheet(isSubmitting = false, onDismiss = onClose, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.bill_split_invitation_title),
            subtitle = stringResource(R.string.bill_split_invitation_sender, row.senderDisplayName), actions = {
                AppSheetActionRow(primary = AppSheetAction(text = stringResource(R.string.bill_split_inbox_accept),
                    enabled = enabled && controls.candidates.any { it.ledgerId == targetId },
                    onClick = { targetId?.let { controls.accept(row.publicId, it); onClose() } }),
                    secondary = AppSheetAction(text = stringResource(R.string.bill_split_back_keep_selection), onClick = onClose))
            }) {
            AppPaperCard(containerColor = LocalThemeVisuals.current.surfaceApricot) {
                Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    Text(stringResource(R.string.bill_split_invitation_share, row.homeCurrencyCode),
                        style = MaterialTheme.typography.bodySmall)
                    AppAmountText(formatDisplayAmount(row.amountCents, CurrencyDisplay.forRecord(row.homeCurrencyCode)),
                        role = AppAmountRole.Hero)
                    row.merchantSnapshot?.let { Text(it) }
                    BillSplitSourceEvidence(row.originalAmountMinor, row.originalCurrencyCode,
                        row.accountingTimeSnapshot, row.expenseTimeSnapshot)
                }
            }
            BillSplitAcceptancePicker(row.publicId, controls, enabled)
            Text(stringResource(if (controls.candidates.isEmpty()) R.string.bill_split_inbox_no_target
                else R.string.bill_split_accept_privacy), style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { onReject(row.publicId); onClose() }, enabled = enabled) {
                Text(stringResource(R.string.bill_split_inbox_reject))
            }
        }
    }
}

/** Inbox and Sync consume the same original acceptance and owner recovery actions. */
@Composable
internal fun BillSplitAcceptanceCard(pending: PendingBillSplitAcceptance, busy: Boolean,
    openBill: ((Long, String) -> Unit)? = null, recover: (Boolean) -> Unit) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(stringResource(R.string.bill_split_accept_recovery))
        pending.payload?.let { original ->
            Text(original.senderName + " · " + original.homeCurrencyCode + " " +
                formatDisplayAmount(original.amountCents, CurrencyDisplay.forRecord(original.homeCurrencyCode)))
            Text(stringResource(R.string.bill_split_accept_original_target, original.targetLedgerName))
        }
        Text(when {
            pending.delivered -> stringResource(R.string.bill_split_action_accepted)
            pending.payload == null -> stringResource(R.string.bill_split_accept_unsupported)
            pending.row.lastError == "bill_split_accept_requires_review" -> stringResource(R.string.bill_split_accept_requires_review)
            pending.row.status in setOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight) -> stringResource(R.string.bill_split_accept_queued)
            listOf("bill_split_accept_response_unverified", "bill_split_accept_connection_interrupted")
                .any { pending.row.lastError?.contains(it) == true } ->
                stringResource(R.string.bill_split_accept_pending)
            else -> friendlyLastError(pending.row.lastError, stringResource(R.string.bill_split_accept_pending))
        })
        if (pending.delivered && openBill != null) pending.invitation?.receivedBill?.let { received ->
            TextButton(onClick = { openBill(received.expenseId, received.ledgerId) }, enabled = !busy) {
                Text(stringResource(R.string.bill_split_open_received))
            }
        }
        if (pending.canRetry) TextButton(onClick = { recover(false) }, enabled = !busy) {
            Text(stringResource(R.string.bill_split_accept_retry))
        }
        if (pending.row.status == PendingMutationStatus.Failed) TextButton(onClick = { confirmDrop = true }, enabled = !busy) {
            Text(stringResource(R.string.bill_split_submission_stop))
        }
    }
    if (confirmDrop) AlertDialog(onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.bill_split_submission_stop)) },
        text = { Text(stringResource(R.string.bill_split_accept_forget_explanation)) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(true) }) { Text(stringResource(R.string.bill_split_submission_stop)) } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(android.R.string.cancel)) } })
}

@Composable
internal fun BillSplitAcceptanceSelection(original: BillSplitAcceptPayload, controls: BillSplitAcceptanceControls,
    busy: Boolean, remove: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(stringResource(R.string.bill_split_accept_unsubmitted))
        Text(original.senderName + " · " + original.homeCurrencyCode + " " +
            formatDisplayAmount(original.amountCents, CurrencyDisplay.forRecord(original.homeCurrencyCode)))
        Text(stringResource(R.string.bill_split_accept_original_target, original.targetLedgerName))
        BillSplitAcceptancePicker(original.publicId, controls, !busy)
        AppPrimaryButton(text = stringResource(R.string.bill_split_inbox_accept),
            enabled = !busy && controls.candidates.any { it.ledgerId == original.targetLedgerId },
            onClick = { controls.accept(original.publicId, original.targetLedgerId) })
        TextButton(onClick = remove, enabled = !busy) { Text(stringResource(R.string.bill_split_accept_remove_selection)) }
    }
}

internal fun androidx.compose.foundation.lazy.LazyListScope.billSplitAcceptanceTasks(
    state: com.ticketbox.viewmodel.BillSplitUiState,
    viewModel: BillSplitViewModel,
    navigation: BillSplitNavigation,
    acceptance: BillSplitAcceptanceControls,
) {
        state.selectedTargets.values.filter { original -> state.inbox.none { it.publicId == original.publicId &&
            it.status == BillSplitStatusValues.INVITED && !it.isInviteLocallyExpired() } }.forEach { original ->
            item(key = "accept-selection-${original.publicId}") { AppPaperCard {
                Column(Modifier.padding(AppSpacing.cardPaddingSmall)) {
                    BillSplitAcceptanceSelection(original, acceptance, state.loading) {
                        state.access?.binding?.let { viewModel.selectTarget(it, original.publicId, null) }
                    }
                }
            } }
        }
        state.acceptances.filter { pending -> !pending.delivered ||
            state.inbox.none { it.publicId == pending.payload?.publicId && it.status == BillSplitStatusValues.ACCEPTED } }.forEach { pending ->
            item(key = "acceptance-${pending.row.id}") { AppPaperCard {
                Column(Modifier.padding(AppSpacing.cardPaddingSmall)) {
                    BillSplitAcceptanceCard(pending, state.loading || navigation.busy, openBill = { expenseId, ledgerId ->
                        state.access?.binding?.let { navigation.openBill(it, expenseId, ledgerId) }
                    }) { drop ->
                        state.access?.binding?.let { viewModel.recoverAcceptance(it, pending.row.id, drop) }
                    }
                }
            } }
        }
}
