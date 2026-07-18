package com.ticketbox.ui.screens.tasks

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import com.ticketbox.R
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.shouldGeneralizeTaskError
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun BackgroundTaskRow(
    task: BackgroundTask,
    busy: Boolean,
    canModify: Boolean,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
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
    Text(
        text = if (busy) {
            stringResource(R.string.background_tasks_row_cancelling)
        } else {
            stringResource(R.string.background_tasks_row_request_cancel)
        },
        color = if (busy) {
            MaterialTheme.colorScheme.onSurfaceVariant
        } else {
            MaterialTheme.colorScheme.primary
        },
        style = MaterialTheme.typography.labelLarge,
        fontWeight = AppTextHierarchy.heading.weight,
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.small))
            .clickable(enabled = !busy, role = Role.Button, onClick = onCancel)
            .padding(horizontal = AppSpacing.miniGap, vertical = AppSpacing.tinyGap),
    )
}
