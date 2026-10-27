package com.ticketbox.ui.screens.settings.categoryrules

import com.ticketbox.viewmodel.CategoryRuleInputError
import com.ticketbox.viewmodel.CategoryRuleDraftForm
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
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.screens.settings.CategoryRuleDefinitionActions
import com.ticketbox.ui.screens.settings.CategoryRulesInteractionState
import com.ticketbox.viewmodel.RuleDefinitionDraftState

@Composable
internal fun CategoryRuleDefinitionEditor(
    state: RuleDefinitionDraftState,
    actions: CategoryRuleDefinitionActions,
    onReturnToCaller: (() -> Unit)?,
) {
    val draft = state.selected ?: return
    var localMessage by remember(draft.key) { mutableStateOf<UiText?>(null) }
    val form = CategoryRuleDraftForm.fromDraft(draft).copy(localMessage = localMessage)
    val bindingChanged = draft.binding != state.binding
    val close = { actions.onClose(); onReturnToCaller?.invoke(); Unit }
    val interaction = CategoryRulesInteractionState(state.busy, bindingChanged || !state.canModify)
    AppBusyGuardedSheet(state.busy, close, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.category_rule_definition_title),
            subtitle = stringResource(R.string.category_rule_definition_subtitle),
            actions = {
                CategoryRuleEditorActions(form, interaction, onSubmit = {
                    form.toRequest().fold(onSuccess = { actions.onSubmit(draft, it) },
                        onFailure = { localMessage = UiText.res((it as? CategoryRuleInputError)?.resourceId
                            ?: R.string.category_rule_validation_fields) })
                }, onCancel = close)
            }) {
        AppStatusBanner(state.error, MessageTone.Danger)
        if (bindingChanged) {
            AppStatusBanner(UiText.res(R.string.category_rule_draft_binding_changed), MessageTone.Info)
            TextButton(enabled = state.canModify && !state.busy, onClick = actions.onReviewBinding) {
                Text(stringResource(R.string.category_rule_draft_review_binding))
            }
        } else if (!state.canModify) {
            AppStatusBanner(UiText.res(R.string.common_readonly_ledger), MessageTone.Info)
        }
        CategoryRuleEditorCard(form, interaction = interaction,
            onFormChange = {
                localMessage = null
                actions.onChange(it.toDraft(draft.binding, draft.key))
            })
        }
    }
}
