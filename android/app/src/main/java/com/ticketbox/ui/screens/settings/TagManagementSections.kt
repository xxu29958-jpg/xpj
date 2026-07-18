package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Label
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.TagUndoHandle

@Immutable
internal data class TagRowActions(
    val onRename: (ManagedTag) -> Unit,
    val onMerge: (ManagedTag) -> Unit,
    val onDelete: (ManagedTag) -> Unit,
)

@Immutable
internal data class TagListState(
    val tags: List<ManagedTag>,
    val bodyState: TagManagementBodyState,
    val readOnly: Boolean,
    val busy: Boolean,
)

@Composable
internal fun rememberTagRowActions(
    onRename: (ManagedTag) -> Unit,
    onMerge: (ManagedTag) -> Unit,
    onDelete: (ManagedTag) -> Unit,
): TagRowActions = remember {
    TagRowActions(
        onRename = onRename,
        onMerge = onMerge,
        onDelete = onDelete,
    )
}

@Composable
internal fun TagUndoPanel(
    handle: TagUndoHandle,
    busy: Boolean,
    onUndo: () -> Unit,
) {
    SettingsOpenPanel {
        AppAdaptiveContentActionRow(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.miniGap),
            content = {
                Text(
                    text = stringResource(R.string.tag_management_undo_processed, handle.label),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            },
        ) { actionModifier ->
            TextButton(modifier = actionModifier, enabled = !busy, onClick = onUndo) {
                Text(stringResource(R.string.tag_management_undo_button))
            }
        }
    }
}

@Composable
internal fun TagSemanticsNote() {
    Text(
        text = stringResource(R.string.tag_management_semantics_note),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
internal fun TagListSection(
    state: TagListState,
    actions: TagRowActions,
) {
    SettingsSection(
        title = stringResource(R.string.tag_management_section_all),
        icon = Icons.AutoMirrored.Filled.Label,
    ) {
        AppSolidCard {
            if (state.bodyState != TagManagementBodyState.Content) {
                SettingsListStateSlot(
                    loading = state.bodyState == TagManagementBodyState.Loading,
                    hasData = false,
                    copy = SettingsStateSlotCopy(
                        loadingTitle = stringResource(R.string.tag_management_loading_title),
                        loadingBody = stringResource(R.string.tag_management_loading_body),
                        emptyText = stringResource(R.string.tag_management_list_empty),
                        emptyTitle = stringResource(R.string.tag_management_summary_empty),
                        emptyBody = stringResource(R.string.tag_management_list_empty),
                    ),
                    message = if (state.bodyState == TagManagementBodyState.LoadFailed) {
                        SettingsStateSlotMessage(
                            text = UiText.res(R.string.tag_management_load_failed),
                            tone = MessageTone.Danger,
                        )
                    } else {
                        null
                    },
                )
                return@AppSolidCard
            }
            Column(
                modifier = Modifier.padding(horizontal = AppSpacing.cardPaddingSmall),
                verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {
                state.tags.forEachIndexed { index, tag ->
                    if (index > 0) {
                        HorizontalDivider(
                            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
                        )
                    }
                    TagRow(
                        tag = tag,
                        readOnly = state.readOnly,
                        busy = state.busy,
                        canMerge = state.tags.size > 1,
                        actions = actions,
                    )
                }
            }
        }
    }
}

@Composable
private fun TagRow(
    tag: ManagedTag,
    readOnly: Boolean,
    busy: Boolean,
    canMerge: Boolean,
    actions: TagRowActions,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = tag.name,
            modifier = Modifier.weight(1f),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = if (tag.usageCount > 0) {
                stringResource(R.string.tag_management_card_usage_count, tag.usageCount)
            } else {
                stringResource(R.string.tag_management_card_orphan)
            },
            color = if (tag.usageCount > 0) {
                MaterialTheme.colorScheme.onSurfaceVariant
            } else {
                MaterialTheme.colorScheme.primary
            },
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
        )
        if (!readOnly) {
            TagActionMenu(tag = tag, busy = busy, canMerge = canMerge, actions = actions)
        }
    }
}

@Composable
private fun TagActionMenu(
    tag: ManagedTag,
    busy: Boolean,
    canMerge: Boolean,
    actions: TagRowActions,
) {
    var expanded by remember(tag.publicId) { mutableStateOf(false) }
    IconButton(
        enabled = !busy,
        onClick = { expanded = true },
    ) {
        Icon(
            imageVector = Icons.Filled.MoreVert,
            contentDescription = stringResource(R.string.tag_management_actions_content_description),
        )
    }
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        DropdownMenuItem(
            text = { Text(stringResource(R.string.tag_management_card_action_rename)) },
            onClick = {
                expanded = false
                actions.onRename(tag)
            },
        )
        DropdownMenuItem(
            text = { Text(stringResource(R.string.tag_management_card_action_merge)) },
            enabled = canMerge,
            onClick = {
                expanded = false
                actions.onMerge(tag)
            },
        )
        DropdownMenuItem(
            text = {
                Text(
                    text = stringResource(R.string.tag_management_card_action_delete),
                    color = MaterialTheme.colorScheme.error,
                )
            },
            onClick = {
                expanded = false
                actions.onDelete(tag)
            },
        )
    }
}
