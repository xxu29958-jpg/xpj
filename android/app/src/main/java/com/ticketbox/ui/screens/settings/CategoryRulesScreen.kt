package com.ticketbox.ui.screens.settings

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleDraftForm
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleEditorCard
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleList
import com.ticketbox.ui.screens.settings.categoryrules.ConfirmedRuleApplyPanel
import com.ticketbox.ui.screens.settings.categoryrules.DeleteCategoryRuleDialog
import com.ticketbox.ui.screens.settings.categoryrules.RuleApplicationHistory
import com.ticketbox.ui.screens.settings.categoryrules.RollbackRuleApplicationDialog

@Composable
fun CategoryRulesScreen(
    rules: List<CategoryRule>,
    busy: Boolean,
    readOnly: Boolean,
    onBack: () -> Unit,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
    applications: List<RuleApplicationBatch>,
    confirmedPreview: RuleApplyConfirmedResult?,
    onPreviewApplyConfirmedRules: () -> Unit,
    onConfirmApplyConfirmedRules: () -> Unit,
    onRollbackRuleApplication: (RuleApplicationBatch) -> Unit,
) {
    var form by remember { mutableStateOf(CategoryRuleDraftForm()) }
    var deletingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var rollbackApplication by remember { mutableStateOf<RuleApplicationBatch?>(null) }

    deletingRule?.let { rule ->
        DeleteCategoryRuleDialog(
            rule = rule,
            onDismiss = { deletingRule = null },
            onConfirm = {
                deletingRule = null
                onDeleteRule(rule)
            },
        )
    }

    rollbackApplication?.let { application ->
        RollbackRuleApplicationDialog(
            application = application,
            onDismiss = { rollbackApplication = null },
            onConfirm = {
                rollbackApplication = null
                onRollbackRuleApplication(application)
            },
        )
    }

    SettingsPageFrame(
        title = "分类规则",
        subtitle = categoryRuleSummary(rules),
        onBack = onBack,
    ) {
        if (!readOnly) {
            SettingsSection(
                title = if (form.editingRule == null) "新增规则" else "编辑规则",
                icon = Icons.Filled.Category,
            ) {
                CategoryRuleEditorCard(
                    form = form,
                    busy = busy,
                    onFormChange = { form = it },
                    onSubmit = {
                        form.submit(
                            onInvalid = { message -> form = form.copy(localMessage = message) },
                            onValid = { rule, keyword, category, priority ->
                                if (rule == null) {
                                    onCreateRule(keyword, category, priority)
                                } else {
                                    onUpdateRule(rule, keyword, category, priority)
                                }
                                form = CategoryRuleDraftForm()
                            },
                        )
                    },
                    onCancel = { form = CategoryRuleDraftForm() },
                )
            }
        } else {
            Text(
                text = "当前角色为只读，无法修改账本。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        SettingsSection(title = "规则列表", icon = Icons.Filled.Category) {
            CategoryRuleList(
                rules = rules,
                readOnly = readOnly,
                onToggleRule = onToggleRule,
                onEditRule = { rule ->
                    if (!readOnly) {
                        form = CategoryRuleDraftForm.fromRule(rule)
                    }
                },
                onDeleteRule = { rule ->
                    if (!readOnly) {
                        deletingRule = rule
                    }
                },
            )
        }
        SettingsSection(title = "已入账应用", icon = Icons.Filled.RestartAlt) {
            ConfirmedRuleApplyPanel(
                preview = confirmedPreview,
                busy = busy,
                readOnly = readOnly,
                onPreview = onPreviewApplyConfirmedRules,
                onConfirm = onConfirmApplyConfirmedRules,
            )
        }
        SettingsSection(title = "最近应用记录", icon = Icons.Filled.RestartAlt) {
            RuleApplicationHistory(
                applications = applications,
                readOnly = readOnly,
                busy = busy,
                onRollback = { application -> rollbackApplication = application },
            )
        }
    }
}

private fun CategoryRuleDraftForm.submit(
    onInvalid: (String) -> Unit,
    onValid: (CategoryRule?, String, String, Int) -> Unit,
) {
    val priority = priorityText.toIntOrNull()
    if (keyword.isBlank() || category.isBlank()) {
        onInvalid("请填写关键词和分类。")
        return
    }
    if (priority == null) {
        onInvalid("优先级必须是数字。")
        return
    }
    onValid(editingRule, keyword, category, priority)
}
