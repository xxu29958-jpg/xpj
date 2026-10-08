package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingCategoryRuleSubmission
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleSubmissionCards
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleDraftForm
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleList
import com.ticketbox.ui.screens.settings.categoryrules.ConfirmedRuleApplyPanel
import com.ticketbox.ui.screens.settings.categoryrules.DeleteCategoryRuleDialog
import com.ticketbox.ui.screens.settings.categoryrules.RuleApplicationHistory
import com.ticketbox.ui.screens.settings.categoryrules.RollbackRuleApplicationDialog
import kotlinx.coroutines.delay
import com.ticketbox.data.repository.RuleDefinitionDraft
import com.ticketbox.viewmodel.RuleDefinitionDraftState
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleDefinitionEditor

data class CategoryRulesScreenState(
    val rules: CategoryRulesRuleListState,
    val interaction: CategoryRulesInteractionState,
    val status: CategoryRulesStatusState,
    val applications: CategoryRulesApplicationState,
    val undoableRule: CategoryRule?,
    val submissions: List<PendingCategoryRuleSubmission> = emptyList(),
    val selectedSubmissionId: Long? = null,
    val submittedRevision: Int = 0,
    val binding: LogicalSessionBinding? = null,
    val definitions: RuleDefinitionDraftState = RuleDefinitionDraftState(),
)

data class CategoryRulesRuleListState(
    val rules: List<CategoryRule>,
    val loading: Boolean,
    val loadFailed: Boolean = false,
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
    val loadFailed: Boolean = false,
)

data class CategoryRulesScreenActions(
    val onBack: () -> Unit,
    val rules: CategoryRulesRuleActions,
    val applications: CategoryRulesApplicationActions,
    val undo: CategoryRulesUndoActions,
    val definitions: CategoryRuleDefinitionActions,
)

data class CategoryRuleDefinitionActions(
    val onBegin: (CategoryRuleDraftForm) -> Unit,
    val onOpen: (RuleDefinitionDraft) -> Unit,
    val onChange: (RuleDefinitionDraft) -> Unit,
    val onSubmit: (RuleDefinitionDraft, CategoryRuleRequest) -> Unit,
    val onClose: () -> Unit,
    val onReviewBinding: () -> Unit,
    val onReload: () -> Unit,
)

data class CategoryRulesRuleActions(
    val onToggle: (CategoryRule) -> Unit,
    val onDelete: (CategoryRule) -> Unit,
    val onRecoverSubmission: (PendingCategoryRuleSubmission, Boolean) -> Unit,
    val onReload: () -> Unit,
)

data class CategoryRulesApplicationActions(
    val onPreviewApplyConfirmedRules: () -> Unit,
    val onConfirmApplyConfirmedRules: () -> Unit,
    val onRollbackRuleApplication: (RuleApplicationBatch) -> Unit,
    val onReload: () -> Unit,
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
    initialRuleId: Long? = null,
) {
    var initialRuleOpened by remember(state.binding, initialRuleId) { mutableStateOf(false) }
    LaunchedEffect(initialRuleId, state.rules.rules, state.interaction.readOnly, state.definitions.ready) {
        if (!initialRuleOpened && !state.interaction.readOnly && state.definitions.ready) {
            state.rules.rules.find { it.id == initialRuleId }?.let {
                actions.definitions.onBegin(CategoryRuleDraftForm.fromRule(it))
                initialRuleOpened = true
            }
        }
    }
    if (state.definitions.selected != null) {
        CategoryRuleDefinitionEditor(state.definitions, actions.definitions, chrome)
        return
    }
    var deletingRule by remember(state.binding) { mutableStateOf<CategoryRule?>(null) }
    var rollbackApplication by remember(state.binding) { mutableStateOf<RuleApplicationBatch?>(null) }

    CategoryRuleDeleteDialogHost(
        rule = deletingRule,
        onDismiss = { deletingRule = null },
        onConfirm = actions.rules.onDelete,
    )
    CategoryRuleRollbackDialogHost(
        application = rollbackApplication,
        onDismiss = { rollbackApplication = null },
        onConfirm = actions.applications.onRollbackRuleApplication,
    )

    ManagementPageFrame(
        header = ManagementPageHeader(
            title = stringResource(R.string.category_rules_page_title),
            subtitle = when {
                state.rules.loading -> stringResource(R.string.category_rules_loading_title)
                state.rules.loadFailed -> stringResource(R.string.category_rules_read_failed_title)
                else -> categoryRuleSummary(state.rules.rules)
            },
            chrome = chrome,
        ),
        onBack = actions.onBack,
        status = { AppStatusBanner(message = state.status.message, tone = state.status.messageTone) },
    ) {
        state.definitions.error?.let {
            AppStatusBanner(message = it, tone = MessageTone.Danger)
            TextButton(onClick = actions.definitions.onReload) { Text(stringResource(R.string.category_rules_reload)) }
        }
        state.definitions.drafts.forEach { draft ->
            SettingsEntryRow(title = draft.keyword.ifBlank { stringResource(R.string.category_rules_section_create) },
                subtitle = stringResource(R.string.category_rule_draft_retained), icon = R.drawable.ic_lucide_tag,
                onClick = { actions.definitions.onOpen(draft) })
        }
        key(state.binding) {
            CategoryRuleSubmissionCards(state.submissions, state.selectedSubmissionId, state.interaction.busy,
                state.interaction.readOnly, actions.rules.onRecoverSubmission)
        }
        CategoryRulesContent(
            state = state.contentState(),
            actions = actions,
            onRequestDelete = { deletingRule = it },
            onRequestRollback = { rollbackApplication = it },
        )
    }
}

private data class CategoryRulesContentState(
    val rules: List<CategoryRule>,
    val rulesLoading: Boolean,
    val rulesLoadFailed: Boolean,
    val busy: Boolean,
    val readOnly: Boolean,
    val applications: List<RuleApplicationBatch>,
    val applicationsLoading: Boolean,
    val applicationsLoadFailed: Boolean,
    val confirmedPreview: RuleApplyConfirmedResult?,
    val undoableRule: CategoryRule?,
    val definitionsReady: Boolean,
)

private fun CategoryRulesScreenState.contentState() = CategoryRulesContentState(
    rules = rules.rules, rulesLoading = rules.loading, rulesLoadFailed = rules.loadFailed, busy = interaction.busy,
    readOnly = interaction.readOnly, applications = applications.history,
    applicationsLoading = applications.loading, confirmedPreview = applications.confirmedPreview,
    applicationsLoadFailed = applications.loadFailed,
    undoableRule = undoableRule,
    definitionsReady = definitions.ready,
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
    actions: CategoryRulesScreenActions,
    onRequestDelete: (CategoryRule) -> Unit,
    onRequestRollback: (RuleApplicationBatch) -> Unit,
) {
    CategoryRuleUndoPanel(
        undoableRule = state.undoableRule,
        onUndoDelete = actions.undo.onUndoDelete,
        onDismissUndo = actions.undo.onDismiss,
    )
    CategoryRuleListSection(
        state = state,
        actions = actions,
        onRequestDelete = onRequestDelete,
    )
    SettingsSection(title = stringResource(R.string.category_rules_section_confirmed_apply)) {
        ConfirmedRuleApplyPanel(
            preview = state.confirmedPreview,
            busy = state.busy,
            readOnly = state.readOnly,
            onPreview = actions.applications.onPreviewApplyConfirmedRules,
            onConfirm = actions.applications.onConfirmApplyConfirmedRules,
        )
    }
    RuleApplicationHistorySection(
        state = state,
        onRequestRollback = onRequestRollback,
        onReload = actions.applications.onReload,
    )
}

@Composable
private fun CategoryRuleListSection(
    state: CategoryRulesContentState,
    actions: CategoryRulesScreenActions,
    onRequestDelete: (CategoryRule) -> Unit,
) {
    SettingsSection(
        title = stringResource(R.string.category_rules_section_list),
        trailing = if (!state.readOnly) {
            {
                TextButton(
                    enabled = !state.busy && state.definitionsReady,
                    onClick = { actions.definitions.onBegin(CategoryRuleDraftForm()) },
                ) {
                    Text(stringResource(R.string.category_rule_editor_submit_create))
                }
            }
        } else {
            null
        },
    ) {
        CategoryRuleListNote(readOnly = state.readOnly)
        CategoryRuleListBody(
            state = state,
            actions = actions,
            onRequestDelete = onRequestDelete,
        )
    }
}

@Composable
private fun CategoryRuleListNote(
    readOnly: Boolean,
) {
    if (readOnly) {
        Text(
            text = stringResource(R.string.common_readonly_ledger),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    } else {
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
    actions: CategoryRulesScreenActions,
    onRequestDelete: (CategoryRule) -> Unit,
) {
    if (state.rulesLoadFailed) {
        SettingsInlineEmpty(
            title = stringResource(R.string.category_rules_read_failed_title),
            body = stringResource(R.string.category_rules_read_failed_body),
        )
        TextButton(enabled = !state.busy, onClick = actions.rules.onReload) { Text(stringResource(R.string.category_rules_reload)) }
    } else if (state.rules.isEmpty()) {
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
            onToggleRule = actions.rules.onToggle,
            onEditRule = { rule ->
                if (!state.readOnly) {
                    actions.definitions.onBegin(CategoryRuleDraftForm.fromRule(rule))
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
private fun RuleApplicationHistorySection(
    state: CategoryRulesContentState,
    onRequestRollback: (RuleApplicationBatch) -> Unit,
    onReload: () -> Unit,
) {
    SettingsSection(title = stringResource(R.string.category_rules_section_history)) {
        if (state.applicationsLoadFailed) {
            SettingsInlineEmpty(
                title = stringResource(R.string.category_rule_history_read_failed_title),
                body = stringResource(R.string.category_rules_read_failed_body),
            )
            TextButton(enabled = !state.busy, onClick = onReload) { Text(stringResource(R.string.category_rule_history_reload)) }
        } else if (state.applications.isEmpty()) {
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
