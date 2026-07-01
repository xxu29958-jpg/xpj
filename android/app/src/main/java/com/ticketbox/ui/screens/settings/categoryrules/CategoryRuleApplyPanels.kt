package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.RuleApplyPreviewItem
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.screens.settings.SettingsOpenPanel

@Composable
internal fun ConfirmedRuleApplyPanel(
    preview: RuleApplyConfirmedResult?,
    busy: Boolean,
    readOnly: Boolean,
    onPreview: () -> Unit,
    onConfirm: () -> Unit,
) {
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
            Text(
                text = stringResource(R.string.category_rule_apply_panel_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            preview?.let { result ->
                ConfirmedRulePreviewSummary(result)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
                OutlinedButton(
                    enabled = !busy,
                    onClick = onPreview,
                ) {
                    Text(
                        if (busy) {
                            stringResource(R.string.category_rule_apply_preview_busy)
                        } else {
                            stringResource(R.string.category_rule_apply_preview_button)
                        },
                    )
                }
                Button(
                    enabled = !busy && !readOnly && (preview?.changedCount ?: 0) > 0,
                    onClick = onConfirm,
                ) {
                    Text(stringResource(R.string.category_rule_apply_confirm_button))
                }
            }
            if (readOnly) {
                Text(
                    text = stringResource(R.string.category_rule_apply_panel_readonly),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
    }
}

@Composable
internal fun RuleApplicationHistory(
    applications: List<RuleApplicationBatch>,
    readOnly: Boolean,
    busy: Boolean,
    onRollback: (RuleApplicationBatch) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (applications.isEmpty()) {
            Text(
                text = stringResource(R.string.category_rule_apply_history_empty),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            applications.forEachIndexed { index, application ->
                RuleApplicationCard(
                    application = application,
                    readOnly = readOnly,
                    busy = busy,
                    onRollback = { onRollback(application) },
                )
                if (index < applications.lastIndex) {
                    HorizontalDivider(
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft),
                    )
                }
            }
        }
    }
}

@Composable
private fun ConfirmedRulePreviewSummary(result: RuleApplyConfirmedResult) {
    Text(
        text = stringResource(
            R.string.category_rule_apply_preview_summary,
            result.confirmedScanned,
            result.changedCount,
            result.noMatchCount,
        ),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    if (result.scanLimitReached) {
        Text(
            text = stringResource(R.string.category_rule_apply_preview_scan_limit, result.scanLimit),
            color = MaterialTheme.colorScheme.secondary,
        )
    }
    result.items.take(5).forEach { item ->
        RuleApplyPreviewRow(item)
    }
}

@Composable
private fun RuleApplyPreviewRow(item: RuleApplyPreviewItem) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.miniGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
            Text(
                text = item.merchant?.takeIf { it.isNotBlank() }
                    ?: stringResource(R.string.category_rule_apply_preview_no_merchant),
                style = MaterialTheme.typography.labelLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = stringResource(
                    R.string.category_rule_apply_preview_mapping,
                    item.currentCategory,
                    item.suggestedCategory,
                    item.ruleKeyword,
                ),
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.bodySmall,
            )
    }
}

@Composable
private fun RuleApplicationCard(
    application: RuleApplicationBatch,
    readOnly: Boolean,
    busy: Boolean,
    onRollback: () -> Unit,
) {
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = if (application.isRolledBack) {
                        stringResource(R.string.category_rule_apply_history_status_rolled_back)
                    } else {
                        stringResource(R.string.category_rule_apply_history_status_applied)
                    },
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = stringResource(R.string.category_rule_apply_history_changed_count, application.changedCount),
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = AppTextHierarchy.body.weight,
                )
            }
            Text(
                text = stringResource(
                    R.string.category_rule_apply_history_scanned,
                    application.pendingScanned,
                    displayTime(application.createdAt),
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            application.rolledBackAt?.let {
                Text(
                    text = stringResource(R.string.category_rule_apply_history_rolled_back_at, displayTime(it)),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (!readOnly && !application.isRolledBack) {
                OutlinedButton(
                    enabled = !busy,
                    onClick = onRollback,
                ) {
                    Text(stringResource(R.string.category_rule_apply_history_rollback_button))
                }
            }
    }
}
