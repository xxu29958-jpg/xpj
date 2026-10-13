package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.PendingRuleApplication
import com.ticketbox.data.repository.PendingCategoryRuleSubmission
import com.ticketbox.ui.components.AppContentCard

@Composable
internal fun RuleSubmissionRecovery(definition: PendingCategoryRuleSubmission?, application: PendingRuleApplication?, open: () -> Unit) {
    if (definition == null && application == null) return
    definition?.let { CategoryRuleSubmissionSummary(it) }
    application?.let { RuleApplicationSubmissionSummary(it) }
    TextButton(onClick = open) {
        Text(stringResource(if (application == null) R.string.category_rule_submission_open else R.string.rule_application_open))
    }
}

@Composable
internal fun RuleApplicationSubmissionSummary(original: PendingRuleApplication) {
    Text(stringResource(R.string.rule_application_original))
    original.original?.let { Text(stringResource(R.string.rule_application_original_counts, it.scanned, it.expectedChanges)) }
    original.receipt?.let {
        Text(stringResource(R.string.rule_application_receipt, it.changedCount))
        if (it.conflictCount > 0) Text(stringResource(R.string.rule_application_conflicts, it.conflictCount))
        if (it.unavailableCount > 0) Text(stringResource(R.string.category_rule_apply_currency_unavailable,
            it.unavailableCount, it.missingCurrencyCodes.joinToString("、")))
        if (it.scanLimitReached) Text(stringResource(R.string.category_rule_apply_preview_scan_limit, it.scanLimit))
    }
    if (original.needsRefresh) Text(stringResource(R.string.rule_application_refresh))
    else if (!original.isDone) Text(stringResource(when (original.row.lastError) {
        "preview_stale", "preview_required" -> R.string.rule_application_stale
        null -> R.string.rule_application_queued
        else -> R.string.rule_application_unverified
    }))
}

@Composable
internal fun RuleApplicationSubmissionCards(rows: List<PendingRuleApplication>, selected: Long?, busy: Boolean,
    readOnly: Boolean, recover: (PendingRuleApplication, Boolean) -> Unit) {
    var stopping by remember { mutableStateOf<PendingRuleApplication?>(null) }
    rows.filter { !it.isDone || it.needsRefresh || it.row.id == selected }.forEach { original ->
        AppContentCard {
            RuleApplicationSubmissionSummary(original)
            if (original.needsRefresh || original.canRetry && !readOnly) TextButton(enabled = !busy, onClick = { recover(original, false) }) {
                Text(stringResource(if (original.needsRefresh) R.string.rule_application_refresh_action else R.string.rule_application_retry))
            }
            if (original.canDrop) TextButton(enabled = !busy, onClick = { stopping = original }) {
                Text(stringResource(R.string.rule_application_stop))
            }
        }
    }
    stopping?.let { original ->
        AlertDialog(onDismissRequest = { stopping = null },
            title = { Text(stringResource(R.string.rule_application_stop)) },
            text = { Column { RuleApplicationSubmissionSummary(original); Text(stringResource(R.string.rule_application_stop_body)) } },
            confirmButton = { TextButton(enabled = !busy, onClick = { stopping = null; recover(original, true) }) {
                Text(stringResource(R.string.rule_application_stop)) } },
            dismissButton = { TextButton(onClick = { stopping = null }) { Text(stringResource(R.string.common_cancel)) } })
    }
}
