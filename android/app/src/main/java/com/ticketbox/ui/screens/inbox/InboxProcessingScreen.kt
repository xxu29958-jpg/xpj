package com.ticketbox.ui.screens.inbox

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.tasks.BackgroundTaskRow
import com.ticketbox.viewmodel.BackgroundTasksUiState

internal enum class InboxProcessingBodyState {
    Loading,
    LoadFailed,
    Empty,
    Content,
}

internal data class InboxProcessingPresentation(
    val bodyState: InboxProcessingBodyState,
    val refreshingWithRows: Boolean,
    val showInlineStatus: Boolean,
)

internal fun inboxProcessingPresentation(
    state: BackgroundTasksUiState,
): InboxProcessingPresentation = InboxProcessingPresentation(
    bodyState = when {
        state.tasks.isNotEmpty() -> InboxProcessingBodyState.Content
        state.loading -> InboxProcessingBodyState.Loading
        state.message != null -> InboxProcessingBodyState.LoadFailed
        else -> InboxProcessingBodyState.Empty
    },
    refreshingWithRows = state.loading && state.tasks.isNotEmpty(),
    showInlineStatus = state.message != null && state.tasks.isNotEmpty(),
)

internal data class InboxProcessingActions(
    val onBack: () -> Unit,
    val onRefresh: () -> Unit,
    val onCancel: (String) -> Unit,
)

@Composable
internal fun InboxProcessingScreen(
    state: BackgroundTasksUiState,
    actions: InboxProcessingActions,
) {
    val presentation = inboxProcessingPresentation(state)
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Pending,
            title = stringResource(R.string.inbox_processing_title),
            subtitle = stringResource(R.string.inbox_processing_subtitle),
            backText = stringResource(R.string.inbox_processing_back),
            onBack = actions.onBack,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = presentation.refreshingWithRows,
            onRefresh = actions.onRefresh,
        ),
    ) {
        if (!state.canModify) {
            item {
                AppDataAuthorityStrip(
                    title = stringResource(R.string.inbox_processing_readonly_title),
                    body = stringResource(R.string.inbox_processing_readonly_body),
                    tone = DataAuthorityTone.ReadOnly,
                )
            }
        }
        if (presentation.showInlineStatus) {
            item { AppStatusBanner(message = state.message, tone = state.messageTone) }
        }
        inboxProcessingContent(
            state = state,
            presentation = presentation,
            onRefresh = actions.onRefresh,
            onCancel = actions.onCancel,
        )
    }
}

private fun LazyListScope.inboxProcessingContent(
    state: BackgroundTasksUiState,
    presentation: InboxProcessingPresentation,
    onRefresh: () -> Unit,
    onCancel: (String) -> Unit,
) {
    when (presentation.bodyState) {
        InboxProcessingBodyState.LoadFailed -> item {
            AppErrorState(
                title = stringResource(R.string.inbox_processing_error_title),
                body = stringResource(R.string.inbox_processing_error_body),
                onRetry = onRefresh,
            )
        }
        InboxProcessingBodyState.Loading,
        InboxProcessingBodyState.Empty,
        -> item {
            InboxProcessingStateCard(
                loading = presentation.bodyState == InboxProcessingBodyState.Loading,
            )
        }
        InboxProcessingBodyState.Content -> items(
            items = state.tasks,
            key = { task -> task.publicId },
        ) { task ->
            AppGlassCard(modifier = Modifier.fillMaxWidth()) {
                BackgroundTaskRow(
                    task = task,
                    busy = state.busyTaskId == task.publicId,
                    canModify = state.canModify,
                    onCancel = { onCancel(task.publicId) },
                    modifier = Modifier.padding(horizontal = AppSpacing.cardPaddingSmall),
                )
            }
        }
    }
}

@Composable
private fun InboxProcessingStateCard(loading: Boolean) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        AppListStateContent(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            state = AppListStateSpec(
                isEmpty = true,
                loading = loading,
                emptyText = stringResource(R.string.inbox_processing_empty_body),
                emptyTitle = stringResource(R.string.inbox_processing_empty_title),
                emptyBody = stringResource(R.string.inbox_processing_empty_body),
            ),
        ) {
        }
    }
}
