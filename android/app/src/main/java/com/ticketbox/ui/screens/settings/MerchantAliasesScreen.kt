package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.MerchantCatalogMergeSuggestion
import com.ticketbox.viewmodel.MerchantEditorCompletion
import com.ticketbox.viewmodel.MerchantEditorKind
import kotlinx.coroutines.delay

@Composable
fun MerchantAliasesScreen(
    state: MerchantAliasesScreenState,
    actions: MerchantAliasesScreenActions,
    chrome: ManagementPageChrome = ManagementPageChrome(),
) {
    val editors = remember { MerchantEditors() }
    val catalogDialogController = editors.catalogDialogs
    // Resolve strings before non-composable click handlers need them.
    val catalogValidationMessage = stringResource(R.string.merchant_catalog_create_validation)
    val createValidationMessage = stringResource(R.string.merchant_aliases_create_validation)

    LaunchedEffect(state.editorCompletion) {
        state.editorCompletion?.let(editors::complete)
    }

    MerchantCatalogDialogHost(
        controller = catalogDialogController,
        state = state,
        actions = MerchantCatalogDialogHostActions(
            onRename = actions.catalog.onRename,
            onMerge = actions.catalog.onMerge,
            onDismissSuggestion = actions.mergeSuggestion.onDismiss,
        ),
    )

    editors.deletingCatalog?.let { item ->
        AlertDialog(
            onDismissRequest = { if (!state.busy) editors.deletingCatalog = null },
            title = { Text(stringResource(R.string.merchant_catalog_delete_dialog_title)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    Text(
                        stringResource(R.string.merchant_catalog_delete_dialog_text, item.displayName),
                    )
                    AppStatusBanner(message = state.message, tone = state.messageTone)
                }
            },
            confirmButton = {
                TextButton(
                    enabled = !state.busy,
                    onClick = { actions.catalog.onDelete(item) },
                ) {
                    Text(stringResource(R.string.merchant_catalog_delete_dialog_confirm), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(enabled = !state.busy, onClick = { editors.deletingCatalog = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    editors.deletingAlias?.let { item ->
        AlertDialog(
            onDismissRequest = { if (!state.busy) editors.deletingAlias = null },
            title = { Text(stringResource(R.string.merchant_aliases_delete_dialog_title)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    Text(
                        stringResource(R.string.merchant_aliases_delete_dialog_text, item.alias, item.canonicalMerchant),
                    )
                    AppStatusBanner(message = state.message, tone = state.messageTone)
                }
            },
            confirmButton = {
                TextButton(
                    enabled = !state.busy,
                    onClick = { actions.alias.onDelete(item) },
                ) {
                    Text(stringResource(R.string.merchant_aliases_delete_dialog_confirm), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(enabled = !state.busy, onClick = { editors.deletingAlias = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    ManagementPageFrame(
        header = ManagementPageHeader(
            title = stringResource(R.string.merchant_aliases_page_title),
            subtitle = merchantAliasSummary(state.catalog, state.aliases),
            chrome = chrome,
        ),
        onBack = actions.onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        // Online deletes expose a short undo window.
        state.undoableAlias?.let { undoable ->
            LaunchedEffect(undoable.publicId) {
                delay(5000)
                actions.undo.onDismiss()
            }
            SettingsOpenPanel {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = AppSpacing.miniGap),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = stringResource(R.string.merchant_aliases_undo_deleted, undoable.alias),
                        modifier = Modifier.weight(1f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.width(AppSpacing.compactGap))
                    TextButton(enabled = !state.busy, onClick = actions.undo.onUndoDelete) {
                        Text(stringResource(R.string.merchant_aliases_undo_button))
                    }
                }
            }
        }

        if (state.readOnly) {
            SettingsInlineEmpty(
                title = stringResource(R.string.merchant_management_readonly_title),
                body = stringResource(R.string.merchant_management_readonly_hint),
            )
        }

        if (!state.readOnly) {
            MerchantManagementToolsSection(
                state = MerchantManagementToolState(
                    activeTool = editors.activeCreateTool,
                    catalogName = editors.catalogName,
                    aliasDraft = MerchantAliasDraft(
                        canonicalMerchant = editors.canonicalMerchant,
                        aliasText = editors.aliasText,
                    ),
                    busy = state.busy,
                    catalogMessage = editors.catalogMessage,
                    aliasMessage = editors.aliasMessage,
                ),
                actions = MerchantManagementToolActions(
                    onStartCatalog = {
                        actions.onStartEditing()
                        editors.activeCreateTool = MerchantCreateTool.Catalog
                        editors.catalogMessage = null
                        editors.aliasMessage = null
                    },
                    onStartAlias = {
                        actions.onStartEditing()
                        editors.activeCreateTool = MerchantCreateTool.Alias
                        editors.catalogMessage = null
                        editors.aliasMessage = null
                    },
                    onCatalogNameChange = { editors.catalogName = it },
                    onAliasDraftChange = {
                        editors.canonicalMerchant = it.canonicalMerchant
                        editors.aliasText = it.aliasText
                    },
                    onSubmitCatalog = {
                        if (editors.catalogName.isBlank()) {
                            editors.catalogMessage = catalogValidationMessage
                        } else {
                            editors.catalogMessage = null
                            actions.catalog.onCreate(editors.catalogName)
                        }
                    },
                    onSubmitAlias = {
                        if (editors.canonicalMerchant.isBlank() || editors.aliasText.isBlank()) {
                            editors.aliasMessage = createValidationMessage
                        } else {
                            editors.aliasMessage = null
                            actions.alias.onCreate(editors.canonicalMerchant, editors.aliasText)
                        }
                    },
                    onCancel = {
                        editors.activeCreateTool = null
                        editors.catalogMessage = null
                        editors.aliasMessage = null
                    },
                ),
            )
        }

        MerchantReferenceLists(state, actions, editors)
    }
}

@Composable
private fun MerchantReferenceLists(
    state: MerchantAliasesScreenState,
    actions: MerchantAliasesScreenActions,
    editors: MerchantEditors,
) {
    if (state.catalog.isEmpty() && state.aliases.isEmpty() && !state.aliasesLoadFailed) {
        SettingsInlineEmpty(
            title = stringResource(R.string.merchant_aliases_empty_combined_title),
            body = stringResource(R.string.merchant_aliases_empty_combined_body),
        )
    } else {
        MerchantCatalogListSection(
            catalog = state.catalog,
            readOnly = state.readOnly,
            busy = state.busy,
            actions = MerchantCatalogListActions(
                onRename = {
                    actions.onStartEditing()
                    editors.catalogDialogs.openRename(it)
                },
                onToggle = actions.catalog.onToggle,
                onMerge = {
                    actions.onStartEditing()
                    editors.catalogDialogs.openMerge(it)
                },
                onDelete = {
                    actions.onStartEditing()
                    editors.deletingCatalog = it
                },
            ),
        )

        if (state.aliasesLoadFailed) {
            SettingsInlineEmpty(
                title = stringResource(R.string.merchant_alias_load_failed),
                body = stringResource(R.string.merchant_aliases_reload_hint),
            )
            TextButton(enabled = !state.busy, onClick = actions.onReloadAliases) {
                Text(stringResource(R.string.merchant_aliases_reload_button))
            }
        } else MerchantAliasListSection(
            aliases = state.aliases,
            readOnly = state.readOnly,
            busy = state.busy,
            onToggleAlias = actions.alias.onToggle,
            onDeleteAlias = {
                actions.onStartEditing()
                editors.deletingAlias = it
            },
        )
    }
}

data class MerchantAliasesScreenState(
    val catalog: List<MerchantCatalog>,
    val aliases: List<MerchantAlias>,
    val aliasesLoadFailed: Boolean,
    val busy: Boolean,
    val readOnly: Boolean,
    val message: UiText?,
    val messageTone: MessageTone = MessageTone.Neutral,
    val undoableAlias: MerchantAlias?,
    val mergeSuggestion: MerchantCatalogMergeSuggestion?,
    val editorCompletion: MerchantEditorCompletion?,
)

data class MerchantAliasesScreenActions(
    val onBack: () -> Unit,
    val onStartEditing: () -> Unit,
    val onReloadAliases: () -> Unit,
    val catalog: MerchantAliasesCatalogActions,
    val alias: MerchantAliasesAliasActions,
    val mergeSuggestion: MerchantAliasesMergeSuggestionActions,
    val undo: MerchantAliasesUndoActions,
)

data class MerchantAliasesCatalogActions(
    val onCreate: (String) -> Unit,
    val onRename: (MerchantCatalog, String) -> Unit,
    val onToggle: (MerchantCatalog) -> Unit,
    val onMerge: (MerchantCatalog, MerchantCatalog, MerchantCatalogAliasPolicy) -> Unit,
    val onDelete: (MerchantCatalog) -> Unit,
)

data class MerchantAliasesAliasActions(
    val onCreate: (String, String) -> Unit,
    val onToggle: (MerchantAlias) -> Unit,
    val onDelete: (MerchantAlias) -> Unit,
)

data class MerchantAliasesMergeSuggestionActions(
    val onDismiss: () -> Unit,
)

data class MerchantAliasesUndoActions(
    val onUndoDelete: () -> Unit,
    val onDismiss: () -> Unit,
)


private class MerchantEditors {
    var catalogName by mutableStateOf("")
    var canonicalMerchant by mutableStateOf("")
    var aliasText by mutableStateOf("")
    var catalogMessage by mutableStateOf<String?>(null)
    var aliasMessage by mutableStateOf<String?>(null)
    var activeCreateTool by mutableStateOf<MerchantCreateTool?>(null)
    var deletingCatalog by mutableStateOf<MerchantCatalog?>(null)
    var deletingAlias by mutableStateOf<MerchantAlias?>(null)
    val catalogDialogs = MerchantCatalogDialogController()

    fun complete(completed: MerchantEditorCompletion) {
        when (completed.kind) {
            MerchantEditorKind.CreateCatalog -> {
                catalogName = ""
                catalogMessage = null
                if (activeCreateTool == MerchantCreateTool.Catalog) activeCreateTool = null
            }
            MerchantEditorKind.CreateAlias -> {
                canonicalMerchant = ""
                aliasText = ""
                aliasMessage = null
                if (activeCreateTool == MerchantCreateTool.Alias) activeCreateTool = null
            }
            MerchantEditorKind.RenameCatalog -> {
                if (catalogDialogs.renamingCatalog?.publicId == completed.publicId) catalogDialogs.closeRename()
            }
            MerchantEditorKind.MergeCatalog -> {
                if (catalogDialogs.mergingCatalog?.publicId == completed.publicId) catalogDialogs.closeMerge()
            }
            MerchantEditorKind.DeleteCatalog -> {
                if (deletingCatalog?.publicId == completed.publicId) deletingCatalog = null
            }
            MerchantEditorKind.DeleteAlias -> {
                if (deletingAlias?.publicId == completed.publicId) deletingAlias = null
            }
        }
    }
}

private enum class MerchantCreateTool {
    Catalog,
    Alias,
}

private data class MerchantAliasDraft(
    val canonicalMerchant: String,
    val aliasText: String,
)

private data class MerchantManagementToolState(
    val activeTool: MerchantCreateTool?,
    val catalogName: String,
    val aliasDraft: MerchantAliasDraft,
    val busy: Boolean,
    val catalogMessage: String?,
    val aliasMessage: String?,
)

private data class MerchantManagementToolActions(
    val onStartCatalog: () -> Unit,
    val onStartAlias: () -> Unit,
    val onCatalogNameChange: (String) -> Unit,
    val onAliasDraftChange: (MerchantAliasDraft) -> Unit,
    val onSubmitCatalog: () -> Unit,
    val onSubmitAlias: () -> Unit,
    val onCancel: () -> Unit,
)

@Composable
private fun MerchantManagementToolsSection(
    state: MerchantManagementToolState,
    actions: MerchantManagementToolActions,
) {
    SettingsSection(title = stringResource(R.string.merchant_management_section_tools)) {
        when (state.activeTool) {
            null -> SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
                ) {
                    Text(
                        text = stringResource(R.string.merchant_management_tools_prompt_title),
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = stringResource(R.string.merchant_management_tools_prompt_body),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                AppActionRow(
                    primary = AppAction(
                        text = stringResource(R.string.merchant_management_tools_add_catalog),
                        enabled = !state.busy,
                        icon = Icons.Filled.Add,
                        onClick = actions.onStartCatalog,
                    ),
                    secondary = AppAction(
                        text = stringResource(R.string.merchant_management_tools_add_alias),
                        enabled = !state.busy,
                        icon = Icons.Filled.Add,
                        onClick = actions.onStartAlias,
                    ),
                )
            }
            MerchantCreateTool.Catalog -> MerchantCatalogCreateSection(
                state = MerchantCatalogCreateState(
                    catalogName = state.catalogName,
                    busy = state.busy,
                    message = state.catalogMessage,
                ),
                actions = MerchantCatalogCreateActions(
                    onCatalogNameChange = actions.onCatalogNameChange,
                    onSubmit = actions.onSubmitCatalog,
                    onCancel = actions.onCancel,
                ),
            )
            MerchantCreateTool.Alias -> MerchantAliasCreateSection(
                state = MerchantAliasCreateState(
                    draft = state.aliasDraft,
                    busy = state.busy,
                    message = state.aliasMessage,
                ),
                actions = MerchantAliasCreateActions(
                    onDraftChange = actions.onAliasDraftChange,
                    onSubmit = actions.onSubmitAlias,
                    onCancel = actions.onCancel,
                ),
            )
        }
    }
}

private data class MerchantCatalogCreateState(
    val catalogName: String,
    val busy: Boolean,
    val message: String?,
)

private data class MerchantCatalogCreateActions(
    val onCatalogNameChange: (String) -> Unit,
    val onSubmit: () -> Unit,
    val onCancel: () -> Unit,
)

@Composable
private fun MerchantCatalogCreateSection(
    state: MerchantCatalogCreateState,
    actions: MerchantCatalogCreateActions,
) {
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        SettingsDialogTextInput(
            state = SettingsTextInputState(
                label = stringResource(R.string.merchant_catalog_name_label),
                value = state.catalogName,
                placeholder = stringResource(R.string.merchant_catalog_name_placeholder),
                enabled = !state.busy,
            ),
            onValueChange = actions.onCatalogNameChange,
        )
        AppActionRow(
            primary = AppAction(
                text = if (state.busy) {
                    stringResource(R.string.merchant_catalog_create_busy)
                } else {
                    stringResource(R.string.merchant_catalog_create_button)
                },
                enabled = !state.busy,
                onClick = actions.onSubmit,
            ),
            secondary = AppAction(
                text = stringResource(R.string.common_cancel),
                enabled = !state.busy,
                onClick = actions.onCancel,
            ),
        )
        state.message?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
    }
}

private data class MerchantAliasCreateState(
    val draft: MerchantAliasDraft,
    val busy: Boolean,
    val message: String?,
)

private data class MerchantAliasCreateActions(
    val onDraftChange: (MerchantAliasDraft) -> Unit,
    val onSubmit: () -> Unit,
    val onCancel: () -> Unit,
)

@Composable
private fun MerchantAliasCreateSection(
    state: MerchantAliasCreateState,
    actions: MerchantAliasCreateActions,
) {
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        SettingsDialogTextInput(
            state = SettingsTextInputState(
                label = stringResource(R.string.merchant_aliases_canonical_label),
                value = state.draft.canonicalMerchant,
                placeholder = stringResource(R.string.merchant_aliases_canonical_placeholder),
                enabled = !state.busy,
            ),
            onValueChange = { actions.onDraftChange(state.draft.copy(canonicalMerchant = it)) },
        )
        SettingsDialogTextInput(
            state = SettingsTextInputState(
                label = stringResource(R.string.merchant_aliases_alias_label),
                value = state.draft.aliasText,
                placeholder = stringResource(R.string.merchant_aliases_alias_placeholder),
                enabled = !state.busy,
            ),
            onValueChange = { actions.onDraftChange(state.draft.copy(aliasText = it)) },
        )
        AppActionRow(
            primary = AppAction(
                text = if (state.busy) {
                    stringResource(R.string.merchant_aliases_create_busy)
                } else {
                    stringResource(R.string.merchant_aliases_create_button)
                },
                enabled = !state.busy,
                onClick = actions.onSubmit,
            ),
            secondary = AppAction(
                text = stringResource(R.string.common_cancel),
                enabled = !state.busy,
                onClick = actions.onCancel,
            ),
        )
        state.message?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
    }
}

@Composable
private fun MerchantAliasListSection(
    aliases: List<MerchantAlias>,
    readOnly: Boolean,
    busy: Boolean,
    onToggleAlias: (MerchantAlias) -> Unit,
    onDeleteAlias: (MerchantAlias) -> Unit,
) {
    SettingsSection(title = stringResource(R.string.merchant_aliases_section_list)) {
        if (aliases.isEmpty()) {
            SettingsInlineEmpty(
                title = stringResource(R.string.merchant_aliases_list_empty_title),
                body = stringResource(R.string.merchant_aliases_list_empty),
            )
            return@SettingsSection
        }
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
            aliases.forEachIndexed { index, item ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
                }
                MerchantAliasRow(
                    alias = item,
                    readOnly = readOnly,
                    busy = busy,
                    onToggleAlias = { onToggleAlias(item) },
                    onDeleteAlias = { onDeleteAlias(item) },
                )
            }
        }
    }
}

@Composable
private fun MerchantAliasRow(
    alias: MerchantAlias,
    readOnly: Boolean,
    busy: Boolean,
    onToggleAlias: () -> Unit,
    onDeleteAlias: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MerchantAliasRowText(
            alias = alias,
            modifier = Modifier.weight(1f),
        )
        MerchantAliasStatus(enabled = alias.enabled)
        if (!readOnly) {
            MerchantAliasActionMenu(
                alias = alias,
                busy = busy,
                onToggleAlias = onToggleAlias,
                onDeleteAlias = onDeleteAlias,
            )
        }
    }
}

@Composable
private fun MerchantAliasRowText(
    alias: MerchantAlias,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = alias.alias,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = stringResource(R.string.merchant_aliases_card_canonical, alias.canonicalMerchant),
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = stringResource(
                R.string.merchant_aliases_card_key_mapping,
                alias.aliasKey,
                alias.canonicalKey,
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun MerchantAliasStatus(enabled: Boolean) {
    Text(
        text = if (enabled) {
            stringResource(R.string.merchant_aliases_card_status_enabled)
        } else {
            stringResource(R.string.merchant_aliases_card_status_disabled)
        },
        color = if (enabled) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        },
        style = MaterialTheme.typography.labelMedium,
        fontWeight = AppTextHierarchy.body.weight,
        maxLines = 1,
    )
}

@Composable
private fun MerchantAliasActionMenu(
    alias: MerchantAlias,
    busy: Boolean,
    onToggleAlias: () -> Unit,
    onDeleteAlias: () -> Unit,
) {
    var expanded by remember(alias.publicId) { mutableStateOf(false) }
    IconButton(
        enabled = !busy,
        onClick = { expanded = true },
    ) {
        Icon(
            imageVector = Icons.Filled.MoreVert,
            contentDescription = stringResource(R.string.merchant_aliases_actions_content_description),
        )
    }
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        DropdownMenuItem(
            text = {
                Text(
                    if (alias.enabled) {
                        stringResource(R.string.merchant_aliases_card_action_disable)
                    } else {
                        stringResource(R.string.merchant_aliases_card_action_enable)
                    },
                )
            },
            onClick = {
                expanded = false
                onToggleAlias()
            },
        )
        DropdownMenuItem(
            text = {
                Text(
                    text = stringResource(R.string.merchant_aliases_card_action_delete),
                    color = MaterialTheme.colorScheme.error,
                )
            },
            onClick = {
                expanded = false
                onDeleteAlias()
            },
        )
    }
}

@Composable
private fun merchantAliasSummary(catalog: List<MerchantCatalog>, aliases: List<MerchantAlias>): String {
    val enabled = aliases.count { it.enabled }
    return if (catalog.isEmpty() && aliases.isEmpty()) {
        stringResource(R.string.merchant_aliases_summary_empty)
    } else {
        stringResource(R.string.merchant_aliases_summary_count, catalog.size, enabled, aliases.size)
    }
}
