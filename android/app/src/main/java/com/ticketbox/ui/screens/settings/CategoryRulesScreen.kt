package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material3.Button
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
    // No default: every caller must wire the ViewModel status channel.
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
    var form by remember { mutableStateOf<CategoryRuleDraftForm?>(null) }
    var deletingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var rollbackApplication by remember { mutableStateOf<RuleApplicationBatch?>(null) }
    val validationFieldsMessage = stringResource(R.string.category_rule_form_validation_fields)
    val validationPriorityMessage = stringResource(R.string.category_rule_form_validation_priority)
    val actions = CategoryRulesActions(
        onCreateRule = onCreateRule,
        onUpdateRule = onUpdateRule,
        onToggleRule = onToggleRule,
        onDeleteRule = onDeleteRule,
        onPreviewApplyConfirmedRules = onPreviewApplyConfirmedRules,
        onConfirmApplyConfirmedRules = onConfirmApplyConfirmedRules,
        onRollbackRuleApplication = onRollbackRuleApplication,
        onUndoDelete = onUndoDelete,
        onDismissUndo = onDismissUndo,
    )

    CategoryRuleDeleteDialogHost(
        rule = deletingRule,
        onDismiss = { deletingRule = null },
        onConfirm = actions.onDeleteRule,
    )
    CategoryRuleRollbackDialogHost(
        application = rollbackApplication,
        onDismiss = { rollbackApplication = null },
        onConfirm = actions.onRollbackRuleApplication,
    )

    SettingsPageFrame(
        title = stringResource(R.string.category_rules_page_title),
        subtitle = categoryRuleSummary(rules),
        onBack = onBack,
        status = { AppStatusBanner(message = message, tone = MessageTone.Neutral) },
    ) {
        CategoryRulesContent(
            state = CategoryRulesContentState(
                rules = rules,
                busy = busy,
                readOnly = readOnly,
                applications = applications,
                confirmedPreview = confirmedPreview,
                undoableRule = undoableRule,
            ),
            editor = CategoryRulesEditorBinding(
                form = form,
                onFormChange = { form = it },
                validationFieldsMessage = validationFieldsMessage,
                validationPriorityMessage = validationPriorityMessage,
            ),
            actions = actions,
            onRequestDelete = { deletingRule = it },
            onRequestRollback = { rollbackApplication = it },
        )
    }
}

private data class CategoryRulesActions(
    val onCreateRule: (String, String, Int) -> Unit,
    val onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    val onToggleRule: (CategoryRule) -> Unit,
    val onDeleteRule: (CategoryRule) -> Unit,
    val onPreviewApplyConfirmedRules: () -> Unit,
    val onConfirmApplyConfirmedRules: () -> Unit,
    val onRollbackRuleApplication: (RuleApplicationBatch) -> Unit,
    val onUndoDelete: () -> Unit,
    val onDismissUndo: () -> Unit,
)

private data class CategoryRulesContentState(
    val rules: List<CategoryRule>,
    val busy: Boolean,
    val readOnly: Boolean,
    val applications: List<RuleApplicationBatch>,
    val confirmedPreview: RuleApplyConfirmedResult?,
    val undoableRule: CategoryRule?,
)

private data class CategoryRulesEditorBinding(
    val form: CategoryRuleDraftForm?,
    val onFormChange: (CategoryRuleDraftForm?) -> Unit,
    val validationFieldsMessage: String,
    val validationPriorityMessage: String,
)

@Composable
private fun CategoryRuleDeleteDialogHost(
    rule: CategoryRule?,
    onDismiss: () -> Unit,
    onConfirm: (CategoryRule) -> Unit,
) {
    rule?.let {
        DeleteCategoryRuleDialog(
            rule = it,
            onDismiss = onDismiss,
            onConfirm = {
                onDismiss()
                onConfirm(it)
            },
        )
    }
}

@Composable
private fun CategoryRuleRollbackDialogHost(
    application: RuleApplicationBatch?,
    onDismiss: () -> Unit,
    onConfirm: (RuleApplicationBatch) -> Unit,
) {
    application?.let {
        RollbackRuleApplicationDialog(
            application = it,
            onDismiss = onDismiss,
            onConfirm = {
                onDismiss()
                onConfirm(it)
            },
        )
    }
}

@Composable
private fun CategoryRulesContent(
    state: CategoryRulesContentState,
    editor: CategoryRulesEditorBinding,
    actions: CategoryRulesActions,
    onRequestDelete: (CategoryRule) -> Unit,
    onRequestRollback: (RuleApplicationBatch) -> Unit,
) {
    CategoryRuleUndoPanel(
        undoableRule = state.undoableRule,
        onUndoDelete = actions.onUndoDelete,
        onDismissUndo = actions.onDismissUndo,
    )
    CategoryRuleCreateSection(
        form = editor.form,
        busy = state.busy,
        readOnly = state.readOnly,
        actions = categoryRuleCreateActions(editor, actions),
    )
    SettingsSection(title = stringResource(R.string.category_rules_section_list), icon = Icons.Filled.Category) {
        CategoryRuleList(
            rules = state.rules,
            readOnly = state.readOnly,
            onToggleRule = actions.onToggleRule,
            onEditRule = { rule ->
                if (!state.readOnly) {
                    editor.onFormChange(CategoryRuleDraftForm.fromRule(rule))
                }
            },
            onDeleteRule = { rule ->
                if (!state.readOnly) {
                    onRequestDelete(rule)
                }
            },
        )
    }
    SettingsSection(title = stringResource(R.string.category_rules_section_confirmed_apply), icon = Icons.Filled.RestartAlt) {
        ConfirmedRuleApplyPanel(
            preview = state.confirmedPreview,
            busy = state.busy,
            readOnly = state.readOnly,
            onPreview = actions.onPreviewApplyConfirmedRules,
            onConfirm = actions.onConfirmApplyConfirmedRules,
        )
    }
    SettingsSection(title = stringResource(R.string.category_rules_section_history), icon = Icons.Filled.RestartAlt) {
        RuleApplicationHistory(
            applications = state.applications,
            readOnly = state.readOnly,
            busy = state.busy,
            onRollback = onRequestRollback,
        )
    }
}

@Composable
private fun CategoryRuleUndoPanel(
    undoableRule: CategoryRule?,
    onUndoDelete: () -> Unit,
    onDismissUndo: () -> Unit,
) {
    undoableRule?.let { undoable ->
        LaunchedEffect(undoable.id) {
            delay(5000)
            onDismissUndo()
        }
        SettingsOpenPanel {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = AppSpacing.miniGap),
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
}

private fun categoryRuleCreateActions(
    editor: CategoryRulesEditorBinding,
    actions: CategoryRulesActions,
): CategoryRuleCreateSectionActions = CategoryRuleCreateSectionActions(
    onStartCreate = { editor.onFormChange(CategoryRuleDraftForm()) },
    onFormChange = editor.onFormChange,
    onSubmit = {
        editor.form?.let { activeForm ->
            activeForm.submit(
                fieldsRequiredMessage = editor.validationFieldsMessage,
                priorityInvalidMessage = editor.validationPriorityMessage,
                onInvalid = { message -> editor.onFormChange(activeForm.copy(localMessage = message)) },
                onValid = { rule, keyword, category, priority ->
                    if (rule == null) {
                        actions.onCreateRule(keyword, category, priority)
                    } else {
                        actions.onUpdateRule(rule, keyword, category, priority)
                    }
                    editor.onFormChange(null)
                },
            )
        }
    },
    onCancel = { editor.onFormChange(null) },
)

private data class CategoryRuleCreateSectionActions(
    val onStartCreate: () -> Unit,
    val onFormChange: (CategoryRuleDraftForm) -> Unit,
    val onSubmit: () -> Unit,
    val onCancel: () -> Unit,
)

@Composable
private fun CategoryRuleCreateSection(
    form: CategoryRuleDraftForm?,
    busy: Boolean,
    readOnly: Boolean,
    actions: CategoryRuleCreateSectionActions,
) {
    if (readOnly) {
        Text(
            text = stringResource(R.string.common_readonly_ledger),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
    SettingsSection(
        title = if (form == null) {
            stringResource(R.string.category_rules_section_manage)
        } else if (form.editingRule == null) {
            stringResource(R.string.category_rules_section_create)
        } else {
            stringResource(R.string.category_rules_section_edit)
        },
        icon = Icons.Filled.Category,
    ) {
        if (form == null) {
            CategoryRuleCreatePrompt(
                busy = busy,
                onStartCreate = actions.onStartCreate,
            )
        } else {
            CategoryRuleEditorCard(
                form = form,
                busy = busy,
                onFormChange = actions.onFormChange,
                onSubmit = actions.onSubmit,
                onCancel = actions.onCancel,
            )
        }
    }
}

@Composable
private fun CategoryRuleCreatePrompt(
    busy: Boolean,
    onStartCreate: () -> Unit,
) {
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = stringResource(R.string.category_rules_create_prompt_title),
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = stringResource(R.string.category_rules_create_prompt_body),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Button(
                enabled = !busy,
                onClick = onStartCreate,
            ) {
                Text(stringResource(R.string.category_rule_editor_submit_create))
            }
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
