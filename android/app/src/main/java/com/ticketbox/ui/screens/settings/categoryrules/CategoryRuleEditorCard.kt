package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.SettingsOpenPanel

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
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
            OutlinedTextField(
                value = form.keyword,
                onValueChange = { onFormChange(form.copy(keyword = it, localMessage = null)) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.category_rule_editor_keyword_label)) },
                placeholder = { Text(stringResource(R.string.category_rule_editor_keyword_placeholder)) },
                singleLine = true,
            )
            OutlinedTextField(
                value = form.category,
                onValueChange = { onFormChange(form.copy(category = it, localMessage = null)) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.category_rule_editor_category_label)) },
                placeholder = { Text(stringResource(R.string.category_rule_editor_category_placeholder)) },
                singleLine = true,
            )
            OutlinedTextField(
                value = form.priorityText,
                onValueChange = { onFormChange(form.copy(priorityText = it, localMessage = null)) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.category_rule_editor_priority_label)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
            )
            Button(
                modifier = Modifier.fillMaxWidth(),
                enabled = !busy,
                onClick = onSubmit,
            ) {
                Text(
                    if (busy) {
                        stringResource(R.string.category_rule_editor_submit_busy)
                    } else if (form.editingRule == null) {
                        stringResource(R.string.category_rule_editor_submit_create)
                    } else {
                        stringResource(R.string.category_rule_editor_submit_update)
                    },
                )
            }
            if (form.editingRule != null) {
                OutlinedButton(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onCancel,
                ) {
                    Text(stringResource(R.string.category_rule_editor_cancel))
                }
            }
            form.localMessage?.let {
                Text(it, color = MaterialTheme.colorScheme.secondary)
            }
    }
}
