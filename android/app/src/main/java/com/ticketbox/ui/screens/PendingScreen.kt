package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.ExpenseCard
import com.ticketbox.viewmodel.PendingUiState

@Composable
fun PendingScreen(
    state: PendingUiState,
    onRefresh: () -> Unit,
    onEdit: (Expense) -> Unit,
    onConfirm: (Expense) -> Unit,
    onReject: (Expense) -> Unit,
    onKeepDuplicate: (Expense) -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        Button(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            onClick = onRefresh,
        ) {
            Text(if (state.loading) "刷新中" else "刷新")
        }

        state.message?.let {
            Text(
                text = it,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                color = MaterialTheme.colorScheme.secondary,
            )
        }

        if (state.items.isEmpty() && !state.loading) {
            Text(
                text = "没有待确认账单",
                modifier = Modifier.padding(16.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(state.items, key = { it.id }) { expense ->
                ExpenseCard(
                    expense = expense,
                    thumbnail = state.thumbnails[expense.id],
                    showActions = true,
                    onEdit = { onEdit(expense) },
                    onConfirm = { onConfirm(expense) },
                    onReject = { onReject(expense) },
                    onKeepDuplicate = { onKeepDuplicate(expense) },
                )
            }
        }
    }
}
