package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.domain.model.SyncQueueFilter
import com.ticketbox.viewmodel.OutboxStatusUiState

internal fun OutboxStatus.filteredQueue(filter: SyncQueueFilter): List<OutboxRow> =
    (queuedRows + failed + conflicts + refreshRequired).distinctBy { it.id }.filter {
        when (filter) {
            SyncQueueFilter.All -> true
            SyncQueueFilter.Uploads -> it.type == PendingMutationType.UploadScreenshot
            SyncQueueFilter.Records -> it.type != PendingMutationType.UploadScreenshot
            SyncQueueFilter.Failed -> it.status == PendingMutationStatus.Failed
        }
    }.sortedWith(compareBy(OutboxRow::createdAt, OutboxRow::id))

@Composable
internal fun SyncQueueFilters(selected: SyncQueueFilter, onSelect: (SyncQueueFilter) -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        SyncQueueFilter.entries.forEach { filter ->
            val label = when (filter) {
                SyncQueueFilter.All -> R.string.widget_queue_all
                SyncQueueFilter.Uploads -> R.string.widget_queue_uploads
                SyncQueueFilter.Records -> R.string.widget_queue_records
                SyncQueueFilter.Failed -> R.string.widget_queue_failures
            }
            FilterChip(selected == filter, onClick = { onSelect(filter) }, label = { Text(stringResource(label)) })
        }
    }
}

/** The existing recovery screen owns retries, original receipts and conflict decisions. */
@Composable
internal fun SyncQueueList(state: OutboxStatusUiState, filter: SyncQueueFilter, onProcess: () -> Unit, onOpenInbox: () -> Unit) {
    if (!state.bindingReady) {
        Text(stringResource(R.string.sync_status_binding_loading))
        return
    }
    val rows = state.status.filteredQueue(filter)
    if (rows.isEmpty()) Text(stringResource(R.string.widget_queue_empty))
    rows.forEach { row ->
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(syncStatusMutationLabelResources.getValue(row.type)))
            val label = when (row.status) {
                PendingMutationStatus.Pending -> R.string.widget_queue_waiting
                PendingMutationStatus.InFlight -> R.string.widget_queue_sending
                PendingMutationStatus.Failed -> R.string.widget_failed
                else -> R.string.widget_queue_conflict
            }
            Text(stringResource(label))
            TextButton(onClick = if (row.type == PendingMutationType.UploadScreenshot) onOpenInbox else onProcess) {
                Text(stringResource(R.string.widget_queue_process))
            }
        }
    }
}
