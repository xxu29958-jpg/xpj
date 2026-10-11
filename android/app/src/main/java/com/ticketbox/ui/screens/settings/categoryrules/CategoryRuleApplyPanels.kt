package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.RuleApplyPreviewItem
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import com.ticketbox.ui.screens.settings.SettingsEntryRowOptions
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationState
import com.ticketbox.ui.screens.settings.CategoryRulesInteractionState
import com.ticketbox.ui.screens.settings.SettingsInlineEmpty
import com.ticketbox.ui.screens.settings.SettingsListStateSlot
import com.ticketbox.ui.screens.settings.SettingsStateSlotCopy
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
            preview?.let { result ->
                ConfirmedRulePreviewSummary(result)
            }
            SettingsEntryRow(stringResource(R.string.category_rule_impact_history_note),
                stringResource(R.string.category_rule_impact_history_body), R.drawable.ic_lucide_info, onClick = null)
            AppActionRow(
                primary = AppAction(
                    text = stringResource(R.string.category_rule_apply_confirm_button),
                    enabled = !busy && !readOnly && preview?.dryRun == true &&
                        !preview.previewToken.isNullOrBlank() && preview.changedCount > 0,
                    onClick = onConfirm,
                ),
                secondary = AppAction(
                    text = if (busy) {
                        stringResource(R.string.category_rule_apply_preview_busy)
                    } else {
                        stringResource(R.string.category_rule_impact_refresh)
                    },
                    enabled = !busy,
                    onClick = onPreview,
                ),
            )
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
    state: CategoryRulesApplicationState,
    interaction: CategoryRulesInteractionState,
    onRollback: (RuleApplicationBatch) -> Unit,
    onReload: () -> Unit,
) {
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
        if (state.loadFailed) {
            SettingsInlineEmpty(stringResource(R.string.category_rule_history_read_failed_title),
                stringResource(R.string.category_rules_read_failed_body))
            TextButton(enabled = !interaction.busy, onClick = onReload) { Text(stringResource(R.string.category_rule_history_reload)) }
        } else if (state.history.isEmpty()) {
            SettingsListStateSlot(loading = state.loading, hasData = false,
                copy = SettingsStateSlotCopy(
                    loadingTitle = stringResource(R.string.category_rule_apply_history_loading_title),
                    loadingBody = stringResource(R.string.category_rule_apply_history_loading_body),
                    emptyText = stringResource(R.string.category_rule_apply_history_empty),
                    emptyTitle = stringResource(R.string.category_rule_apply_history_empty),
                    emptyBody = ""))
        } else {
            state.history.forEachIndexed { index, application ->
                RuleApplicationRow(
                    application = application,
                    readOnly = interaction.readOnly,
                    busy = interaction.busy,
                    onRollback = { onRollback(application) },
                )
                if (index < state.history.lastIndex) {
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
    AppPaperCard(containerColor = LocalThemeVisuals.current.brandPrimaryBg) {
        Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(R.string.category_rule_impact_changes), style = MaterialTheme.typography.labelLarge)
            Text(stringResource(R.string.category_rule_impact_count, result.changedCount),
                style = MaterialTheme.typography.displaySmall.tabularNum(), fontWeight = AppTextHierarchy.heading.weight)
            Text(stringResource(R.string.category_rule_impact_scope), style = MaterialTheme.typography.bodyMedium)
        }
    }
    SettingsEntryRow(stringResource(R.string.category_rule_impact_preserved),
        stringResource(R.string.category_rule_impact_preserved_count, result.skippedNonDefaultCategory),
        R.drawable.ic_lucide_shield_check, onClick = null)
    SettingsEntryRow(stringResource(R.string.category_rule_impact_unchanged),
        stringResource(R.string.category_rule_impact_unchanged_count, result.noMatchCount, result.unchangedCount),
        R.drawable.ic_lucide_check, onClick = null)
    if (result.unavailableCount > 0) {
        Text(stringResource(R.string.category_rule_apply_currency_unavailable, result.unavailableCount,
            result.missingCurrencyCodes.joinToString("、")), color = MaterialTheme.colorScheme.secondary)
    }
    if (result.scanLimitReached) {
        Text(
            text = stringResource(R.string.category_rule_apply_preview_scan_limit, result.scanLimit),
            color = MaterialTheme.colorScheme.secondary,
        )
    }
    if (result.items.isNotEmpty()) {
        var expanded by rememberSaveable(result.previewToken) { mutableStateOf(false) }
        SettingsEntryRow(stringResource(R.string.category_rule_impact_samples, result.items.size),
            stringResource(R.string.category_rule_impact_samples_hint), R.drawable.ic_lucide_receipt_text,
            onClick = { expanded = !expanded }, options = SettingsEntryRowOptions(expanded = expanded))
        if (expanded) result.items.forEach { item -> RuleApplyPreviewRow(item) }
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
private fun RuleApplicationRow(
    application: RuleApplicationBatch,
    readOnly: Boolean,
    busy: Boolean,
    onRollback: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = stringResource(when {
                        application.status == "rollback_partial" -> R.string.category_rule_apply_history_status_partial
                        application.status == "rollback_skipped" -> R.string.category_rule_apply_history_status_skipped
                        application.isRolledBack -> R.string.category_rule_apply_history_status_rolled_back
                        else -> R.string.category_rule_apply_history_status_applied
                    }),
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
                val outcomes = application.changeCounts
                Text(
                    text = if (outcomes == null) stringResource(R.string.category_rule_apply_history_outcomes_unknown)
                    else stringResource(R.string.category_rule_apply_history_outcomes,
                        outcomes["rolled_back"] ?: 0, outcomes["skipped"] ?: 0),
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = stringResource(R.string.category_rule_apply_history_rolled_back_at, displayTime(it)),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(stringResource(R.string.category_rule_apply_history_outcome_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall)
            }
            if (!readOnly && !application.isRolledBack) {
                AppSecondaryButton(
                    text = stringResource(R.string.category_rule_apply_history_rollback_button),
                    enabled = !busy,
                    onClick = onRollback,
                )
            }
    }
}
