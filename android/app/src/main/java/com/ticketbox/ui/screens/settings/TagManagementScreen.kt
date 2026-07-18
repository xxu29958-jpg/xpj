package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.TagManagementUiState
import com.ticketbox.viewmodel.TagManagementViewModel
import kotlinx.coroutines.delay

@Composable
fun TagManagementScreen(
    viewModel: TagManagementViewModel,
    readOnly: Boolean,
    onBack: () -> Unit,
    onTagsChanged: () -> Unit = {},
    chrome: ManagementPageChrome = ManagementPageChrome(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var renaming by remember { mutableStateOf<ManagedTag?>(null) }
    var merging by remember { mutableStateOf<ManagedTag?>(null) }
    var deleting by remember { mutableStateOf<ManagedTag?>(null) }
    var preselectedMergeTarget by remember { mutableStateOf<ManagedTag?>(null) }
    val rowActions = rememberTagRowActions(
        onRename = { tag -> renaming = tag },
        onMerge = { tag ->
            preselectedMergeTarget = null
            merging = tag
        },
        onDelete = { tag -> deleting = tag },
    )

    // After a committed tag mutation, refresh stats filters that may still show old names.
    LaunchedEffect(state.tagsChangedRevision) {
        if (state.tagsChangedRevision > 0) onTagsChanged()
    }

    // Rename collisions become an explicit user-confirmed merge.
    LaunchedEffect(state.mergeSuggestion) {
        state.mergeSuggestion?.let { suggestion ->
            preselectedMergeTarget = suggestion.target
            merging = suggestion.source
            viewModel.consumeMergeSuggestion()
        }
    }

    TagManagementDialogHost(
        state = TagManagementDialogState(
            renaming = renaming,
            merging = merging,
            deleting = deleting,
            tags = state.tags,
            preselectedMergeTarget = preselectedMergeTarget,
            busy = state.busy,
        ),
        actions = TagManagementDialogActions(
            onRenameConfirm = { tag, newName ->
                viewModel.renameTag(tag, newName)
                renaming = null
            },
            onMergeConfirm = { source, target ->
                viewModel.mergeTags(source, target)
                merging = null
                preselectedMergeTarget = null
            },
            onDeleteConfirm = { tag ->
                deleting = null
                viewModel.deleteTag(tag)
            },
            onDismissRename = { renaming = null },
            onDismissMerge = {
                merging = null
                preselectedMergeTarget = null
            },
            onDismissDelete = { deleting = null },
        ),
    )

    TagManagementPageContent(
        state = state,
        readOnly = readOnly,
        actions = TagManagementPageActions(
            onBack = onBack,
            rowActions = rowActions,
            onUndo = viewModel::undo,
            onDismissUndo = viewModel::dismissUndo,
        ),
        chrome = chrome,
    )
}

private data class TagManagementPageActions(
    val onBack: () -> Unit,
    val rowActions: TagRowActions,
    val onUndo: () -> Unit,
    val onDismissUndo: () -> Unit,
)

@Composable
private fun TagManagementPageContent(
    state: TagManagementUiState,
    readOnly: Boolean,
    actions: TagManagementPageActions,
    chrome: ManagementPageChrome,
) {
    val bodyState = remember(state.tags, state.loading, state.loadFailed) {
        tagManagementBodyState(
            hasTags = state.tags.isNotEmpty(),
            loading = state.loading,
            loadFailed = state.loadFailed,
        )
    }
    ManagementPageFrame(
        header = ManagementPageHeader(
            title = stringResource(R.string.tag_management_page_title),
            subtitle = tagSummary(state.tags, bodyState),
            chrome = chrome,
        ),
        onBack = actions.onBack,
        status = {
            if (bodyState != TagManagementBodyState.LoadFailed) {
                AppStatusBanner(message = state.message, tone = state.messageTone)
            }
        },
    ) {
        state.undoable?.let { handle ->
            TagUndoPanel(handle = handle, busy = state.busy, onUndo = actions.onUndo)
            LaunchedEffect(handle.mutationPublicId) {
                delay(5000)
                actions.onDismissUndo()
            }
        }
        if (readOnly) {
            SettingsInlineEmpty(
                title = stringResource(R.string.tag_management_readonly_title),
                body = stringResource(R.string.tag_management_readonly_hint),
            )
        }
        if (bodyState == TagManagementBodyState.Content || bodyState == TagManagementBodyState.Empty) {
            TagSemanticsNote()
        }
        TagListSection(
            state = TagListState(
                tags = state.tags,
                bodyState = bodyState,
                readOnly = readOnly,
                busy = state.busy,
            ),
            actions = actions.rowActions,
        )
    }
}

@Composable
private fun tagSummary(tags: List<ManagedTag>, bodyState: TagManagementBodyState): String {
    when (bodyState) {
        TagManagementBodyState.Loading -> return stringResource(R.string.tag_management_loading_title)
        TagManagementBodyState.LoadFailed -> return stringResource(R.string.tag_management_load_failed)
        TagManagementBodyState.Empty -> return stringResource(R.string.tag_management_summary_empty)
        TagManagementBodyState.Content -> Unit
    }
    val summary = tagManagementSummaryModel(tags)
    return if (summary.unusedCount > 0) {
        stringResource(R.string.tag_management_summary_with_unused, summary.totalCount, summary.unusedCount)
    } else {
        stringResource(R.string.tag_management_summary_count, summary.totalCount)
    }
}
