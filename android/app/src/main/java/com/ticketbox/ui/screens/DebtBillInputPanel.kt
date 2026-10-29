package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.DebtBillTaskAction
import com.ticketbox.viewmodel.DebtListUiState
import com.ticketbox.viewmodel.DebtListViewModel

/** Both Debt and Relations use this original-task consumer inside their shared form. */
@Composable
internal fun DebtBillInputPanel(state: DebtListUiState, model: DebtListViewModel, onPickOriginal: () -> Unit) {
    if (state.billInputs.isEmpty() && state.activeBillCaptureKey == null) return
    Column {
        if (state.activeBillCaptureKey != null && state.activeBill == null) {
            DebtBillOriginalRow(listOf(stringResource(R.string.debt_bill_local_save_unverified)), readable = false,
                showDivider = state.billInputs.isNotEmpty()) {
                AppSecondaryButton(text = stringResource(R.string.debt_bill_retry_capture), onClick = onPickOriginal,
                    enabled = state.canPrepareBill)
            }
        }
        state.billInputs.forEachIndexed { index, input ->
            DebtBillInputRow(input, state, model, showDivider = index < state.billInputs.lastIndex)
        }
    }
    state.billPreview?.let { DebtBillOriginalDialog(it, model::dismissFlash) }
}

@Composable
private fun DebtBillInputRow(input: com.ticketbox.data.repository.DebtBillInput, state: DebtListUiState,
    model: DebtListViewModel, showDivider: Boolean) {
    val status = stringResource(when {
        input.source?.parseOutcome?.status == "failed" -> R.string.debt_bill_suggestion_failed_kept
        input.source != null -> R.string.debt_bill_source_retained
        input.needsAttention -> R.string.debt_bill_capture_needs_attention
        else -> R.string.debt_bill_capture_waiting
    })
    DebtBillOriginalRow(listOf(input.payload.file.metadata.fileName, status), readable = true, showDivider = showDivider) {
        AppSecondaryButton(text = stringResource(R.string.debt_bill_continue_original),
            onClick = { model.billTask(input.captureKey, DebtBillTaskAction.Resume) }, enabled = !state.isSubmitting)
        TextButton(onClick = { model.billTask(input.captureKey, DebtBillTaskAction.Preview) }) {
            Text(stringResource(R.string.debt_bill_view_original))
        }
        if (state.activeBillCaptureKey == input.captureKey && !state.publicationUnverified) {
            TextButton(onClick = { model.billTask(input.captureKey, if (input.source == null)
                DebtBillTaskAction.RetryCapture else DebtBillTaskAction.Parse) },
                enabled = state.canModify && !state.isSubmitting && !state.isParsingBill) {
                Text(stringResource(if (input.source == null) R.string.debt_bill_retry_capture else R.string.debt_bill_retry_suggestion))
            }
        }
    }
}

/**
 * One original-bill row for the Debt detail and the creation form: the same entry-row language as the
 * detail's facts. A tappable row opens its original; [actions] keep the form's explicit tasks.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun DebtBillOriginalRow(lines: List<String>, readable: Boolean, showDivider: Boolean,
    onClick: (() -> Unit)? = null, actions: (@Composable () -> Unit)? = null) {
    val visuals = LocalThemeVisuals.current
    AppListRow(onClick = onClick, showDivider = showDivider) {
        SettingsEntryIcon(ImageVector.vectorResource(if (readable) R.drawable.ic_lucide_scan_line else R.drawable.ic_lucide_info),
            Modifier.padding(end = AppSpacing.contentGap), background = if (readable) visuals.brandPrimaryBg else visuals.surfaceLilac)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(stringResource(R.string.debt_bill_originals), style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight)
            lines.forEach { line ->
                Text(line, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            actions?.let { content ->
                FlowRow(Modifier.fillMaxWidth().padding(top = AppSpacing.miniGap),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) { content() }
            }
        }
        if (onClick != null) Icon(ImageVector.vectorResource(R.drawable.ic_lucide_chevron_right), contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.align(Alignment.CenterVertically))
    }
}

@Composable
internal fun DebtBillOriginalDialog(bytes: ByteArray, onDismiss: () -> Unit) {
    val image = remember(bytes) { com.ticketbox.domain.model.ProtectedImage(bytes, null) }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(stringResource(R.string.debt_bill_view_original)) },
        text = { com.ticketbox.ui.components.AppAsyncImage(image, Modifier.fillMaxWidth()) },
        confirmButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_confirm)) } })
}
