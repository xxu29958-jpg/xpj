package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleDraftForm
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleEditorCard
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleList
import com.ticketbox.ui.screens.settings.categoryrules.ConfirmedRuleApplyPanel
import com.ticketbox.ui.screens.settings.categoryrules.DeleteCategoryRuleDialog
import com.ticketbox.ui.screens.settings.categoryrules.RuleApplicationHistory
import com.ticketbox.ui.screens.settings.categoryrules.RollbackRuleApplicationDialog
import kotlinx.coroutines.delay

@Composable
fun CategoryRulesScreen(
    rules: List<CategoryRule>,
    busy: Boolean,
    readOnly: Boolean,
    // No default on purpose: the compiler forces every caller to wire the
    // VM message through (this channel was silently dead before).
    message: UiText?,
    onBack: () -> Unit,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
    applications: List<RuleApplicationBatch>,
    confirmedPreview: RuleApplyConfirmedResult?,
    onPreviewApplyConfirmedRules: () -> Unit,
    onConfirmApplyConfirmedRules: () -> Unit,
    onRollbackRuleApplication: (RuleApplicationBatch) -> Unit,
    undoableRule: CategoryRule? = null,
    onUndoDelete: () -> Unit = {},
    onDismissUndo: () -> Unit = {},
) {
    var form by remember { mutableStateOf(CategoryRuleDraftForm()) }
    var deletingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var rollbackApplication by remember { mutableStateOf<RuleApplicationBatch?>(null) }
    val validationFieldsMessage = stringResource(R.string.category_rule_form_validation_fields)
    val validationPriorityMessage = stringResource(R.string.category_rule_form_validation_priority)

    deletingRule?.let { rule ->
        DeleteCategoryRuleDialog(
            rule = rule,
            onDismiss = { deletingRule = null },
            onConfirm = {
                deletingRule = null
                onDeleteRule(rule)
            },
        )
    }

    rollbackApplication?.let { application ->
        RollbackRuleApplicationDialog(
            application = application,
            onDismiss = { rollbackApplication = null },
            onConfirm = {
                rollbackApplication = null
                onRollbackRuleApplication(application)
            },
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.category_rules_page_title),
        subtitle = categoryRuleSummary(rules),
        onBack = onBack,
        status = { AppStatusBanner(message = message, tone = MessageTone.Neutral) },
    ) {
        // ADR-0038 undo: a soft-deleted rule is recoverable for a 5s window.
        // Online-only (shown only after a synced delete); auto-dismisses.
        undoableRule?.let { undoable ->
            LaunchedEffect(undoable.id) {
                delay(5000)
                onDismissUndo()
            }
            AppGlassCard(containerAlpha = 0.98f) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(AppSpacing.compactGap),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = stringResource(R.string.category_rules_undo_deleted, undoable.keyword),
                        modifier = Modifier.weight(1f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.width(AppSpacing.compactGap))
                    TextButton(onClick = onUndoDelete) { Text(stringResource(R.string.category_rules_undo_button)) }
                }
            }
        }
        if (!readOnly) {
            SettingsSection(
                title = if (form.editingRule == null) {
                    stringResource(R.string.category_rules_section_create)
                } else {
                    stringResource(R.string.category_rules_section_edit)
                },
                icon = Icons.Filled.Category,
            ) {
                CategoryRuleEditorCard(
                    form = form,
                    busy = busy,
                    onFormChange = { form = it },
                    onSubmit = {
                        form.submit(
                            fieldsRequiredMessage = validationFieldsMessage,
                            priorityInvalidMessage = validationPriorityMessage,
                            onInvalid = { message -> form = form.copy(localMessage = message) },
                            onValid = { rule, keyword, category, priority ->
                                if (rule == null) {
                                    onCreateRule(keyword, category, priority)
                                } else {
                                    onUpdateRule(rule, keyword, category, priority)
                                }
                                form = CategoryRuleDraftForm()
                            },
                        )
                    },
                    onCancel = { form = CategoryRuleDraftForm() },
                )
            }
        } else {
            Text(
                text = stringResource(R.string.common_readonly_ledger),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        SettingsSection(title = stringResource(R.string.category_rules_section_list), icon = Icons.Filled.Category) {
            CategoryRuleList(
                rules = rules,
                readOnly = readOnly,
                onToggleRule = onToggleRule,
                onEditRule = { rule ->
                    if (!readOnly) {
                        form = CategoryRuleDraftForm.fromRule(rule)
                    }
                },
                onDeleteRule = { rule ->
                    if (!readOnly) {
                        deletingRule = rule
                    }
                },
            )
        }
        SettingsSection(title = stringResource(R.string.category_rules_section_confirmed_apply), icon = Icons.Filled.RestartAlt) {
            ConfirmedRuleApplyPanel(
                preview = confirmedPreview,
                busy = busy,
                readOnly = readOnly,
                onPreview = onPreviewApplyConfirmedRules,
                onConfirm = onConfirmApplyConfirmedRules,
            )
        }
        SettingsSection(title = stringResource(R.string.category_rules_section_history), icon = Icons.Filled.RestartAlt) {
            RuleApplicationHistory(
                applications = applications,
                readOnly = readOnly,
                busy = busy,
                onRollback = { application -> rollbackApplication = application },
            )
        }
    }
}

private fun CategoryRuleDraftForm.submit(
    fieldsRequiredMessage: String,
    priorityInvalidMessage: String,
    onInvalid: (String) -> Unit,
    onValid: (CategoryRule?, String, String, Int) -> Unit,
) {
    val priority = priorityText.toIntOrNull()
    if (keyword.isBlank() || category.isBlank()) {
        onInvalid(fieldsRequiredMessage)
        return
    }
    if (priority == null) {
        onInvalid(priorityInvalidMessage)
        return
    }
    onValid(editingRule, keyword, category, priority)
}
