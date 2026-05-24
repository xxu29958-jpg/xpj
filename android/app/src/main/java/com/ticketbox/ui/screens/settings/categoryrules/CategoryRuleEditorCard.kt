package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.AppSpacing

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
    AppGlassCard(containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingTight),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            OutlinedTextField(
                value = form.keyword,
                onValueChange = { onFormChange(form.copy(keyword = it, localMessage = null)) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("商家关键词") },
                placeholder = { Text("OpenAI") },
                singleLine = true,
            )
            OutlinedTextField(
                value = form.category,
                onValueChange = { onFormChange(form.copy(category = it, localMessage = null)) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("推荐分类") },
                placeholder = { Text("AI订阅") },
                singleLine = true,
            )
            OutlinedTextField(
                value = form.priorityText,
                onValueChange = { onFormChange(form.copy(priorityText = it, localMessage = null)) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("优先级") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
            )
            Button(
                modifier = Modifier.fillMaxWidth(),
                enabled = !busy,
                onClick = onSubmit,
            ) {
                Text(if (busy) "处理中" else if (form.editingRule == null) "添加规则" else "保存规则")
            }
            if (form.editingRule != null) {
                OutlinedButton(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onCancel,
                ) {
                    Text("取消编辑")
                }
            }
            form.localMessage?.let {
                Text(it, color = MaterialTheme.colorScheme.secondary)
            }
        }
    }
}
