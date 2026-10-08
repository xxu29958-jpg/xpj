package com.ticketbox.ui.screens.settings.categoryrules

import androidx.activity.compose.BackHandler
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.screens.settings.CategoryRuleDefinitionActions
import com.ticketbox.ui.screens.settings.CategoryRulesInteractionState
import com.ticketbox.ui.screens.settings.ManagementPageChrome
import com.ticketbox.ui.screens.settings.ManagementPageFrame
import com.ticketbox.ui.screens.settings.ManagementPageHeader
import com.ticketbox.viewmodel.RuleDefinitionDraftState

@Composable
internal fun CategoryRuleDefinitionEditor(
    state: RuleDefinitionDraftState,
    actions: CategoryRuleDefinitionActions,
    chrome: ManagementPageChrome,
) {
    val draft = state.selected ?: return
    var localMessage by remember(draft.key) { mutableStateOf<UiText?>(null) }
    val form = CategoryRuleDraftForm.fromDraft(draft).copy(localMessage = localMessage)
    val bindingChanged = draft.binding != state.binding
    BackHandler(onBack = actions.onClose)
    ManagementPageFrame(
        header = ManagementPageHeader(stringResource(R.string.category_rule_definition_title),
            stringResource(R.string.category_rule_definition_subtitle),
            chrome.copy(backText = stringResource(R.string.category_rules_page_title))),
        onBack = actions.onClose,
        status = { AppStatusBanner(state.error, MessageTone.Danger) },
    ) {
        if (bindingChanged) {
            AppStatusBanner(UiText.res(R.string.category_rule_draft_binding_changed), MessageTone.Info)
            TextButton(enabled = state.canModify && !state.busy, onClick = actions.onReviewBinding) {
                Text(stringResource(R.string.category_rule_draft_review_binding))
            }
        } else if (!state.canModify) {
            AppStatusBanner(UiText.res(R.string.common_readonly_ledger), MessageTone.Info)
        }
        CategoryRuleEditorCard(form, interaction = CategoryRulesInteractionState(state.busy, bindingChanged || !state.canModify),
            onFormChange = {
                localMessage = null
                actions.onChange(it.toDraft(draft.binding, draft.key))
            },
            onSubmit = {
                form.toRequest().fold(onSuccess = { actions.onSubmit(draft, it) },
                    onFailure = { localMessage = UiText.res((it as? CategoryRuleInputError)?.resourceId
                        ?: R.string.category_rule_validation_fields) })
            },
            onCancel = actions.onClose)
    }
}
