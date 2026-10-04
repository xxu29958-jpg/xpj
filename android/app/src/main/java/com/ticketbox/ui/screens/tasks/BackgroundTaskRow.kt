package com.ticketbox.ui.screens.tasks

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.shouldGeneralizeTaskError
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun BackgroundTaskRow(
    task: BackgroundTask,
    busy: Boolean,
    canModify: Boolean,
    onCancel: () -> Unit,
    onOpenSource: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        BackgroundTaskTitleLine(
            task = task,
            busy = busy,
            canModify = canModify,
            onCancel = onCancel,
        )
        BackgroundTaskTimeLines(task)
        BackgroundTaskProgress(task)
        BackgroundTaskMessage(task)
        BackgroundTaskError(task)
        if (task.taskType == "orphan_inspection" || task.taskType == "orphan_disposal") {
            Text(stringResource(R.string.background_tasks_original_maintenance_source),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (task.sourceExpenseId != null) {
            TextButton(onClick = onOpenSource) { Text(stringResource(R.string.background_tasks_open_source)) }
        } else if (task.taskType == "expense_enrichment") {
            Text(stringResource(R.string.background_tasks_source_unavailable),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun BackgroundTaskTitleLine(
    task: BackgroundTask,
    busy: Boolean,
    canModify: Boolean,
    onCancel: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SettingsEntryIcon(icon = when (task.taskType) {
            "expense_enrichment" -> Icons.Filled.Image
            "csv_import" -> Icons.Filled.FileDownload
            "expense_fx" -> Icons.Filled.Sync
            else -> Icons.Filled.Tune
        })
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(backgroundTaskTypeLabelRes(task.taskType)),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(backgroundTaskStatusLabelRes(task.status)),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.secondary,
            )
        }
        if (canCancelBackgroundTask(task, canModify)) {
            BackgroundTaskCancelAction(busy = busy, onCancel = onCancel)
        }
    }
}

@Composable
private fun BackgroundTaskTimeLines(task: BackgroundTask) {
    Text(
        text = stringResource(R.string.background_tasks_row_created, displayTime(task.createdAt)),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    task.completedAt?.let {
        Text(
            text = stringResource(R.string.background_tasks_row_finished, displayTime(it)),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun BackgroundTaskProgress(task: BackgroundTask) {
    val progressTotal = task.progressTotal ?: return
    if (progressTotal <= 0) return
    val progressCurrent = task.progressCurrent.coerceIn(0, progressTotal)
    Text(
        text = stringResource(R.string.background_tasks_row_progress, progressCurrent, progressTotal),
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    LinearProgressIndicator(
        progress = { progressCurrent.toFloat() / progressTotal.toFloat() },
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun BackgroundTaskMessage(task: BackgroundTask) {
    task.progressMessage?.takeIf { it.isNotBlank() }?.let {
        Text(
            text = it,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun BackgroundTaskError(task: BackgroundTask) {
    task.errorMessage?.takeIf { it.isNotBlank() }?.let { rawError ->
        val genericError = stringResource(R.string.background_tasks_row_error_generic)
        Text(
            text = if (shouldGeneralizeTaskError(rawError)) genericError else rawError,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

@Composable
private fun BackgroundTaskCancelAction(
    busy: Boolean,
    onCancel: () -> Unit,
) {
    TextButton(enabled = !busy, onClick = onCancel) {
        Text(
            text = if (busy) {
                stringResource(R.string.background_tasks_row_cancelling)
            } else {
                stringResource(R.string.background_tasks_row_request_cancel)
            },
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
    }
}
