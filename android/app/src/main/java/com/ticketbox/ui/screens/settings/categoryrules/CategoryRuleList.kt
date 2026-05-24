package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.CategoryRuleCard

@Composable
internal fun CategoryRuleList(
    rules: List<CategoryRule>,
    readOnly: Boolean,
    onToggleRule: (CategoryRule) -> Unit,
    onEditRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (rules.isEmpty()) {
            Text(
                text = "暂无分类规则。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            rules.forEach { rule ->
                CategoryRuleCard(
                    rule = rule,
                    readOnly = readOnly,
                    onToggleRule = onToggleRule,
                    onEditRule = { onEditRule(rule) },
                    onDeleteRule = { onDeleteRule(rule) },
                )
            }
        }
    }
}
