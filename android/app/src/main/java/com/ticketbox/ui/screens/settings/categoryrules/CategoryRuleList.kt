package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.screens.settings.CategoryRuleCard
import com.ticketbox.ui.screens.settings.SettingsOpenPanel

@Composable
internal fun CategoryRuleList(
    rules: List<CategoryRule>,
    readOnly: Boolean,
    onToggleRule: (CategoryRule) -> Unit,
    onEditRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
) {
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
        if (rules.isEmpty()) {
            Text(
                text = stringResource(R.string.category_rule_list_empty),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            rules.forEachIndexed { index, rule ->
                if (index > 0) {
                    HorizontalDivider(
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
                    )
                }
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
