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

data class CategoryRulesScreenState(
    val rules: CategoryRulesRuleListState,
    val interaction: CategoryRulesInteractionState,
    val status: CategoryRulesStatusState,
    val applications: CategoryRulesApplicationState,
    val undoableRule: CategoryRule?,
)

data class CategoryRulesRuleListState(
    val rules: List<CategoryRule>,
    val loading: Boolean,
)

data class CategoryRulesInteractionState(
    val busy: Boolean,
    val readOnly: Boolean,
)

data class CategoryRulesStatusState(
    val message: UiText?,
    val messageTone: MessageTone,
)

data class CategoryRulesApplicationState(
    val history: List<RuleApplicationBatch>,
    val loading: Boolean,
    val confirmedPreview: RuleApplyConfirmedResult?,
)

data class CategoryRulesScreenActions(
    val onBack: () -> Unit,
    val rules: CategoryRulesRuleActions,
    val applications: CategoryRulesApplicationActions,
    val undo: CategoryRulesUndoActions,
)

data class CategoryRulesRuleActions(
    val onCreate: (String, String, Int) -> Unit,
    val onUpdate: (CategoryRule, String, String, Int) -> Unit,
    val onToggle: (CategoryRule) -> Unit,
    val onDelete: (CategoryRule) -> Unit,
)

data class CategoryRulesApplicationActions(
    val onPreviewApplyConfirmedRules: () -> Unit,
    val onConfirmApplyConfirmedRules: () -> Unit,
    val onRollbackRuleApplication: (RuleApplicationBatch) -> Unit,
)

data class CategoryRulesUndoActions(
    val onUndoDelete: () -> Unit,
    val onDismiss: () -> Unit,
)

@Composable
fun CategoryRulesScreen(
    state: CategoryRulesScreenState,
    actions: CategoryRulesScreenActions,
    chrome: ManagementPageChrome = ManagementPageChrome(),
) {
    var form by remember { mutableStateOf<CategoryRuleDraftForm?>(null) }
    var deletingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var rollbackApplication by remember { mutableStateOf<RuleApplicationBatch?>(null) }
    val validationFieldsMessage = stringResource(R.string.category_rule_form_validation_fields)
    val validationPriorityMessage = stringResource(R.string.category_rule_form_validation_priority)
    val contentActions = CategoryRulesActions(
        onCreateRule = actions.rules.onCreate,
        onUpdateRule = actions.rules.onUpdate,
        onToggleRule = actions.rules.onToggle,
        onDeleteRule = actions.rules.onDelete,
        onPreviewApplyConfirmedRules = actions.applications.onPreviewApplyConfirmedRules,
        onConfirmApplyConfirmedRules = actions.applications.onConfirmApplyConfirmedRules,
        onRollbackRuleApplication = actions.applications.onRollbackRuleApplication,
        onUndoDelete = actions.undo.onUndoDelete,
        onDismissUndo = actions.undo.onDismiss,
    )

    CategoryRuleDeleteDialogHost(
        rule = deletingRule,
        onDismiss = { deletingRule = null },
        onConfirm = contentActions.onDeleteRule,
    )
    CategoryRuleRollbackDialogHost(
        application = rollbackApplication,
        onDismiss = { rollbackApplication = null },
        onConfirm = contentActions.onRollbackRuleApplication,
    )

    ManagementPageFrame(
        header = ManagementPageHeader(
            title = stringResource(R.string.category_rules_page_title),
            subtitle = categoryRuleSummary(state.rules.rules),
            chrome = chrome,
        ),
        onBack = actions.onBack,
        status = { AppStatusBanner(message = state.status.message, tone = state.status.messageTone) },
    ) {
        CategoryRulesContent(
            state = CategoryRulesContentState(
                rules = state.rules.rules,
                rulesLoading = state.rules.loading,
                busy = state.interaction.busy,
                readOnly = state.interaction.readOnly,
                applications = state.applications.history,
                applicationsLoading = state.applications.loading,
                confirmedPreview = state.applications.confirmedPreview,
                undoableRule = state.undoableRule,
            ),
            editor = CategoryRulesEditorBinding(
                form = form,
                onFormChange = { form = it },
                validationFieldsMessage = validationFieldsMessage,
                validationPriorityMessage = validationPriorityMessage,
            ),
            actions = contentActions,
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
    val rulesLoading: Boolean,
    val busy: Boolean,
    val readOnly: Boolean,
    val applications: List<RuleApplicationBatch>,
    val applicationsLoading: Boolean,
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
    CategoryRuleListSection(
        state = state,
        editor = editor,
        actions = actions,
        onRequestDelete = onRequestDelete,
    )
    SettingsSection(title = stringResource(R.string.category_rules_section_confirmed_apply), icon = Icons.Filled.RestartAlt) {
        ConfirmedRuleApplyPanel(
            preview = state.confirmedPreview,
            busy = state.busy,
            readOnly = state.readOnly,
            onPreview = actions.onPreviewApplyConfirmedRules,
            onConfirm = actions.onConfirmApplyConfirmedRules,
        )
    }
    RuleApplicationHistorySection(
        state = state,
        onRequestRollback = onRequestRollback,
    )
}

@Composable
private fun CategoryRuleListSection(
    state: CategoryRulesContentState,
    editor: CategoryRulesEditorBinding,
    actions: CategoryRulesActions,
    onRequestDelete: (CategoryRule) -> Unit,
) {
    val form = editor.form
    SettingsSection(
        title = stringResource(R.string.category_rules_section_list),
        icon = Icons.Filled.Category,
        trailing = if (!state.readOnly && form == null) {
            {
                TextButton(
                    enabled = !state.busy,
                    onClick = { editor.onFormChange(CategoryRuleDraftForm()) },
                ) {
                    Text(stringResource(R.string.category_rule_editor_submit_create))
                }
            }
        } else {
            null
        },
    ) {
        CategoryRuleListNote(readOnly = state.readOnly, hasActiveForm = form != null)
        if (form != null && !state.readOnly) {
            CategoryRuleEditorSlot(
                form = form,
                busy = state.busy,
                editor = editor,
                actions = actions,
            )
        }
        CategoryRuleListBody(
            state = state,
            editor = editor,
            actions = actions,
            onRequestDelete = onRequestDelete,
        )
    }
}

@Composable
private fun CategoryRuleListNote(
    readOnly: Boolean,
    hasActiveForm: Boolean,
) {
    if (readOnly) {
        Text(
            text = stringResource(R.string.common_readonly_ledger),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    } else if (!hasActiveForm) {
        Text(
            text = stringResource(R.string.category_rules_create_prompt_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun CategoryRuleListBody(
    state: CategoryRulesContentState,
    editor: CategoryRulesEditorBinding,
    actions: CategoryRulesActions,
    onRequestDelete: (CategoryRule) -> Unit,
) {
    if (state.rules.isEmpty()) {
        SettingsListStateSlot(
            loading = state.rulesLoading,
            hasData = false,
            copy = SettingsStateSlotCopy(
                loadingTitle = stringResource(R.string.category_rules_loading_title),
                loadingBody = stringResource(R.string.category_rules_loading_body),
                emptyText = stringResource(R.string.category_rule_list_empty),
                emptyTitle = stringResource(R.string.category_rules_summary_empty),
                emptyBody = stringResource(R.string.category_rule_list_empty),
            ),
        )
    } else {
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
}

@Composable
private fun CategoryRuleEditorSlot(
    form: CategoryRuleDraftForm,
    busy: Boolean,
    editor: CategoryRulesEditorBinding,
    actions: CategoryRulesActions,
) {
    Text(
        text = stringResource(
            if (form.editingRule == null) {
                R.string.category_rules_section_create
            } else {
                R.string.category_rules_section_edit
            },
        ),
        style = MaterialTheme.typography.titleSmall,
    )
    CategoryRuleEditorCard(
        form = form,
        busy = busy,
        onFormChange = editor.onFormChange,
        onSubmit = {
            form.submit(
                fieldsRequiredMessage = editor.validationFieldsMessage,
                priorityInvalidMessage = editor.validationPriorityMessage,
                onInvalid = { message -> editor.onFormChange(form.copy(localMessage = message)) },
                onValid = { rule, keyword, category, priority ->
                    if (rule == null) {
                        actions.onCreateRule(keyword, category, priority)
                    } else {
                        actions.onUpdateRule(rule, keyword, category, priority)
                    }
                    editor.onFormChange(null)
                },
            )
        },
        onCancel = { editor.onFormChange(null) },
    )
}

@Composable
private fun RuleApplicationHistorySection(
    state: CategoryRulesContentState,
    onRequestRollback: (RuleApplicationBatch) -> Unit,
) {
    SettingsSection(title = stringResource(R.string.category_rules_section_history), icon = Icons.Filled.RestartAlt) {
        if (state.applications.isEmpty()) {
            SettingsListStateSlot(
                loading = state.applicationsLoading,
                hasData = false,
                copy = SettingsStateSlotCopy(
                    loadingTitle = stringResource(R.string.category_rule_apply_history_loading_title),
                    loadingBody = stringResource(R.string.category_rule_apply_history_loading_body),
                    emptyText = stringResource(R.string.category_rule_apply_history_empty),
                    emptyTitle = stringResource(R.string.category_rule_apply_history_empty),
                    emptyBody = stringResource(R.string.category_rule_apply_history_empty),
                ),
            )
        } else {
            RuleApplicationHistory(
                applications = state.applications,
                readOnly = state.readOnly,
                busy = state.busy,
                onRollback = onRequestRollback,
            )
        }
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
