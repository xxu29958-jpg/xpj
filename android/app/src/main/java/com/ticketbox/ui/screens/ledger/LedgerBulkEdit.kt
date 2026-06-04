package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.screens.expense.ExpenseEditCategoryField

/**
 * ADR-0042 Slice C: in-content contextual action bar shown while the ledger is
 * in multi-select mode (the ledger has no own TopAppBar to transform). Close /
 * "已选 N 笔" / 全选 / 编辑, mirroring the /web 「本页批处理」 affordance rendered
 * natively. "编辑" opens [LedgerBulkEditSheet].
 */
@Composable
internal fun LedgerSelectionBar(
    selectedCount: Int,
    applying: Boolean,
    onExit: () -> Unit,
    onSelectAll: () -> Unit,
    onEdit: () -> Unit,
) {
    AppGlassCard(modifier = Modifier.fillMaxWidth(), containerAlpha = 0.99f) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onExit, enabled = !applying) {
                Icon(Icons.Filled.Close, contentDescription = "退出多选")
            }
            Text(
                text = "已选 $selectedCount 笔",
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onSelectAll, enabled = !applying) { Text("全选") }
            Button(onClick = onEdit, enabled = selectedCount > 0 && !applying) { Text("编辑") }
        }
    }
}

/**
 * ADR-0042 Slice C: bulk-edit sheet for the selected confirmed expenses.
 * Category is the primary action; tags are opt-in (off by default) because the
 * client sends the WHOLE tag string — applying tags REPLACES, not merges. When
 * any selected row already has tags the replace is gated behind a confirm
 * dialog. Category and tags are independent actions (mirrors /web's two submits).
 */
@Composable
internal fun LedgerBulkEditSheet(
    selectedCount: Int,
    selectedHaveTags: Boolean,
    categories: List<String>,
    applying: Boolean,
    onApplyCategory: (String) -> Unit,
    onApplyTags: (String) -> Unit,
) {
    var category by rememberSaveable { mutableStateOf("") }
    var tagsEnabled by rememberSaveable { mutableStateOf(false) }
    var tags by rememberSaveable { mutableStateOf("") }
    var showTagConfirm by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(text = "批量编辑 $selectedCount 笔", style = MaterialTheme.typography.titleMedium)

        // 分类 —— 主操作。
        ExpenseEditCategoryField(
            category = category,
            categories = categories,
            onCategoryChange = { category = it },
            enabled = !applying,
        )
        Button(
            onClick = { onApplyCategory(category) },
            enabled = category.isNotBlank() && !applying,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("应用分类到 $selectedCount 笔")
        }

        // 标签 —— 默认关闭；整串替换语义，需显式开启。
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = "替换标签",
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.weight(1f),
            )
            Switch(checked = tagsEnabled, onCheckedChange = { tagsEnabled = it }, enabled = !applying)
        }
        if (tagsEnabled) {
            OutlinedTextField(
                value = tags,
                onValueChange = { tags = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("标签") },
                placeholder = { Text("真香、必要支出") },
                singleLine = true,
                enabled = !applying,
            )
            Text(
                text = "将整串覆盖所选账单的现有标签。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
            Button(
                // Require non-blank tags — symmetric with the category button.
                // Bulk-clearing tags isn't a stated use case and an empty replace
                // would silently wipe every selected row's tags.
                onClick = { if (selectedHaveTags) showTagConfirm = true else onApplyTags(tags) },
                enabled = tags.isNotBlank() && !applying,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("替换标签到 $selectedCount 笔")
            }
        }
    }

    if (showTagConfirm) {
        AlertDialog(
            onDismissRequest = { showTagConfirm = false },
            title = { Text("替换标签？") },
            text = { Text("所选账单的现有标签将被整串覆盖。") },
            confirmButton = {
                TextButton(onClick = {
                    showTagConfirm = false
                    onApplyTags(tags)
                }) { Text("替换") }
            },
            dismissButton = {
                TextButton(onClick = { showTagConfirm = false }) { Text("取消") }
            },
        )
    }
}
