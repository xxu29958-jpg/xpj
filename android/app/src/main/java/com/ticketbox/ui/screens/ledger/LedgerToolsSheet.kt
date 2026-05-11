package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.screens.CategoryFilterRow
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun LedgerToolsSheet(
    state: LedgerUiState,
    canExport: Boolean,
    onCategoryChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
    onDismiss: () -> Unit,
) {
    val hasUserFilters = state.categoryFilter.isNotBlank() || state.query.isNotBlank()
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("筛选与更新", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black)
            Text(
                text = ledgerCombinedStatusLine(state),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        CategoryFilterRow(
            categories = state.categories,
            selectedCategory = state.categoryFilter,
            onCategoryChange = onCategoryChange,
        )
        OutlinedTextField(
            value = state.query,
            onValueChange = onQueryChange,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            placeholder = { Text("搜索备注") },
            singleLine = true,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            LedgerInlineButton(
                text = if (state.exporting) "导出中" else "导出表格",
                modifier = Modifier.weight(1f),
                enabled = canExport,
                onClick = onExportCsv,
            )
            LedgerInlineButton(
                text = if (state.syncing) "更新中" else "更新账本",
                modifier = Modifier.weight(1f),
                enabled = !state.syncing,
                onClick = onSync,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (hasUserFilters) {
                QuietOutlinedButton(
                    text = "清除筛选",
                    modifier = Modifier.weight(1f),
                    onClick = onClearFilters,
                )
            }
            Button(
                modifier = Modifier.weight(1f),
                onClick = onDismiss,
            ) {
                Text("完成")
            }
        }
        if (state.items.isEmpty()) {
            Text(
                text = "当前没有可导出的已确认账单。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
