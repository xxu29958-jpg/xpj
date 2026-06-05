package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.viewmodel.BillSplitViewModel

/** ADR-0029 bill split UI: two tabs (Inbox / Sent), actions per row. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BillSplitScreen(
    viewModel: BillSplitViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsState()
    var selectedTab by remember { mutableStateOf(0) }

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("拆账") },
                navigationIcon = {
                    OutlinedButton(onClick = onBack) { Text("返回") }
                },
            )
        },
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxWidth()) {
            TabRow(selectedTabIndex = selectedTab) {
                Tab(
                    selected = selectedTab == 0,
                    onClick = { selectedTab = 0 },
                    text = { Text("收件箱 (${state.inbox.size})") },
                )
                Tab(
                    selected = selectedTab == 1,
                    onClick = { selectedTab = 1 },
                    text = { Text("已发出 (${state.sent.size})") },
                )
            }
            state.message?.let {
                Text(
                    it,
                    modifier = Modifier.padding(12.dp),
                    color = MaterialTheme.colorScheme.error,
                )
            }
            if (selectedTab == 0) {
                InboxList(
                    inbox = state.inbox,
                    onAccept = viewModel::accept,
                    onReject = viewModel::reject,
                    candidateTargetLedgerIds = state.candidateTargetLedgerIds,
                )
            } else {
                SentList(sent = state.sent, onCancel = viewModel::cancel)
            }
        }
    }
}

@Composable
private fun InboxList(
    inbox: List<BillSplitInbox>,
    onAccept: (String, String) -> Unit,
    onReject: (String) -> Unit,
    candidateTargetLedgerIds: List<String>,
) {
    if (inbox.isEmpty()) {
        EmptyState(text = "暂无拆账邀请。")
        return
    }
    LazyColumn(contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(inbox, key = { it.publicId }) { row ->
            InboxRow(
                row = row,
                onAccept = onAccept,
                onReject = onReject,
                candidateTargetLedgerIds = candidateTargetLedgerIds,
            )
        }
    }
}

@Composable
private fun InboxRow(
    row: BillSplitInbox,
    onAccept: (String, String) -> Unit,
    onReject: (String) -> Unit,
    candidateTargetLedgerIds: List<String>,
) {
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(row.senderDisplayName, fontWeight = FontWeight.SemiBold)
            Text(formatAmount(row.amountCents))
        }
        Text(
            text = "${row.merchantSnapshot ?: "—"} · ${row.categorySuggestion ?: "—"} · ${row.status}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        if (row.status == BillSplitStatusValues.INVITED) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                candidateTargetLedgerIds.firstOrNull()?.let { firstLedger ->
                    OutlinedButton(onClick = { onAccept(row.publicId, firstLedger) }) {
                        Text("接受到 $firstLedger")
                    }
                }
                OutlinedButton(onClick = { onReject(row.publicId) }) { Text("拒绝") }
            }
        }
    }
}

@Composable
private fun SentList(
    sent: List<BillSplitSent>,
    onCancel: (String) -> Unit,
) {
    if (sent.isEmpty()) {
        EmptyState(text = "暂无已发出的拆账邀请。")
        return
    }
    LazyColumn(contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(sent, key = { it.publicId }) { row ->
            SentRow(row = row, onCancel = onCancel)
        }
    }
}

@Composable
private fun SentRow(
    row: BillSplitSent,
    onCancel: (String) -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(row.receiverDisplayNameSnapshot ?: "—", fontWeight = FontWeight.SemiBold)
            Text(formatAmount(row.amountCents))
        }
        Text(
            text = "${row.merchantSnapshot ?: "—"} · ${row.status}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        if (row.status == BillSplitStatusValues.INVITED) {
            OutlinedButton(onClick = { onCancel(row.publicId) }) { Text("撤回") }
        }
    }
}

@Composable
private fun EmptyState(text: String) {
    Text(text = text, modifier = Modifier.padding(24.dp))
}
