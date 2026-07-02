package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.SettingsDialogTextInput
import com.ticketbox.ui.screens.settings.SettingsOpenPanel
import com.ticketbox.ui.screens.settings.SettingsTextInputState

data class CategoryRuleDraftForm(
    val keyword: String = "",
    val category: String = "",
    val priorityText: String = "10",
    val editingRule: CategoryRule? = null,
    val localMessage: String? = null,
) {
    companion object {
        fun fromRule(rule: CategoryRule): CategoryRuleDraftForm = CategoryRuleDraftForm(
            keyword = rule.keyword,
            category = rule.category,
            priorityText = rule.priority.toString(),
            editingRule = rule,
        )
    }
}

@Composable
internal fun CategoryRuleEditorCard(
    form: CategoryRuleDraftForm,
    busy: Boolean,
    onFormChange: (CategoryRuleDraftForm) -> Unit,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        CategoryRuleEditorFields(form = form, busy = busy, onFormChange = onFormChange)
        CategoryRuleEditorActions(
            form = form,
            busy = busy,
            onSubmit = onSubmit,
            onCancel = onCancel,
        )
        form.localMessage?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
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
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
    ) {
        SettingsDialogTextInput(
            state = SettingsTextInputState(
                label = stringResource(R.string.category_rule_editor_category_label),
                value = form.category,
                placeholder = stringResource(R.string.category_rule_editor_category_placeholder),
                enabled = !busy,
            ),
            onValueChange = { onFormChange(form.copy(category = it, localMessage = null)) },
            modifier = Modifier.weight(1.15f),
        )
        SettingsDialogTextInput(
            state = SettingsTextInputState(
                label = stringResource(R.string.category_rule_editor_priority_label),
                value = form.priorityText,
                enabled = !busy,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            ),
            onValueChange = { onFormChange(form.copy(priorityText = it, localMessage = null)) },
            modifier = Modifier.weight(0.85f),
        )
    }
}

@Composable
private fun CategoryRuleEditorActions(
    form: CategoryRuleDraftForm,
    busy: Boolean,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
    ) {
        if (form.editingRule != null) {
            OutlinedButton(
                modifier = Modifier.weight(1f),
                onClick = onCancel,
            ) {
                Text(stringResource(R.string.category_rule_editor_cancel))
            }
        }
        Button(
            modifier = Modifier.weight(1f),
            enabled = !busy,
            onClick = onSubmit,
        ) {
            Text(categoryRuleSubmitLabel(busy = busy, editing = form.editingRule != null))
        }
    }
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
