package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.SettingsDialogTextInput
import com.ticketbox.ui.screens.settings.SettingsOpenPanel
import com.ticketbox.ui.screens.settings.SettingsTextInputState
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import com.ticketbox.ui.screens.settings.SettingsEntryRowOptions
import com.ticketbox.ui.screens.settings.CategoryRulesInteractionState

@Composable
internal fun CategoryRuleEditorCard(
    form: CategoryRuleDraftForm,
    interaction: CategoryRulesInteractionState,
    onFormChange: (CategoryRuleDraftForm) -> Unit,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        val disabled = interaction.busy || interaction.readOnly
        CategoryRuleEditorFields(form = form, busy = disabled, onFormChange = onFormChange)
        CategoryRuleOptionalFields(form, disabled, onFormChange)
        Text(stringResource(R.string.category_rule_definition_hint), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        CategoryRuleEditorActions(
            form = form,
            interaction = interaction,
            onSubmit = onSubmit,
            onCancel = onCancel,
        )
        form.localMessage?.let {
            Text(it.asString(), color = MaterialTheme.colorScheme.secondary)
        }
    }
}

@Composable
private fun CategoryRuleEditorFields(
    form: CategoryRuleDraftForm,
    busy: Boolean,
    onFormChange: (CategoryRuleDraftForm) -> Unit,
) {
    SettingsDialogTextInput(
        state = SettingsTextInputState(
            label = stringResource(R.string.category_rule_editor_keyword_label),
            value = form.keyword,
            placeholder = stringResource(R.string.category_rule_editor_keyword_placeholder),
            enabled = !busy,
        ),
        onValueChange = { onFormChange(form.copy(keyword = it, localMessage = null)) },
    )
    SettingsDialogTextInput(
        state = SettingsTextInputState(
            label = stringResource(R.string.category_rule_editor_category_label),
            value = form.category,
            placeholder = stringResource(R.string.category_rule_editor_category_placeholder),
            enabled = !busy,
        ),
        onValueChange = { onFormChange(form.copy(category = it, localMessage = null)) },
    )
    SettingsDialogTextInput(
        state = SettingsTextInputState(
            label = stringResource(R.string.category_rule_editor_priority_label),
            value = form.priorityText,
            enabled = !busy,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        ),
        onValueChange = { onFormChange(form.copy(priorityText = it, localMessage = null)) },
    )
}

@Composable
private fun CategoryRuleOptionalFields(form: CategoryRuleDraftForm, busy: Boolean, onChange: (CategoryRuleDraftForm) -> Unit) {
    val hasAmount = form.minimumAmount.isNotBlank() || form.maximumAmount.isNotBlank()
    val hasConditions = form.sourceContains.isNotBlank() || form.tagContains.isNotBlank()
    var amountOpen by remember { mutableStateOf(hasAmount) }
    var conditionsOpen by remember { mutableStateOf(hasConditions) }
    SettingsEntryRow(stringResource(R.string.category_rule_definition_amount),
        stringResource(if (hasAmount) R.string.category_rule_definition_configured else R.string.category_rule_definition_optional),
        R.drawable.ic_lucide_sliders_horizontal, { amountOpen = !amountOpen }, SettingsEntryRowOptions(expanded = amountOpen))
    if (amountOpen) CategoryRuleAmountFields(form, busy, onChange)
    SettingsEntryRow(stringResource(R.string.category_rule_definition_conditions),
        stringResource(if (hasConditions) R.string.category_rule_definition_configured else R.string.category_rule_definition_optional),
        R.drawable.ic_lucide_tag, { conditionsOpen = !conditionsOpen }, SettingsEntryRowOptions(expanded = conditionsOpen))
    if (conditionsOpen) {
        SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.category_rule_definition_source),
            value = form.sourceContains, enabled = !busy), onValueChange = { onChange(form.copy(sourceContains = it, localMessage = null)) })
        SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.category_rule_definition_tag),
            value = form.tagContains, enabled = !busy), onValueChange = { onChange(form.copy(tagContains = it, localMessage = null)) })
    }
}

@Composable
private fun CategoryRuleEditorActions(
    form: CategoryRuleDraftForm,
    interaction: CategoryRulesInteractionState,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    AppActionRow(
        primary = AppAction(
            text = categoryRuleSubmitLabel(busy = interaction.busy, editing = form.editingRule != null),
            enabled = !interaction.busy && !interaction.readOnly,
            onClick = onSubmit,
        ),
        secondary = AppAction(
                text = stringResource(R.string.category_rule_editor_cancel),
                onClick = onCancel,
            ),
    )
}

@Composable
private fun categoryRuleSubmitLabel(
    busy: Boolean,
    editing: Boolean,
): String = when {
    busy -> stringResource(R.string.category_rule_editor_submit_busy)
    editing -> stringResource(R.string.category_rule_editor_submit_update)
    else -> stringResource(R.string.category_rule_editor_submit_create)
}
