package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
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

    LaunchedEffect(state.editorCompletion) {
        state.editorCompletion?.let(editors::complete)
    }
    LaunchedEffect(state.undoableAlias?.publicId) {
        if (state.undoableAlias != null) {
            delay(5000)
            actions.undo.onDismiss()
        }
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

    val selected = state.catalog.find { it.publicId == editors.selectedCatalogId }
    val pages = rememberSaveableStateHolder()
    val onBack = { if (editors.isDirectory) actions.onBack() else editors.back() }
    BackHandler(enabled = !editors.isDirectory, onBack = onBack)
    pages.SaveableStateProvider(editors.pageKey) {
        ManagementPageFrame(
            header = merchantPageHeader(editors, selected, chrome),
            onBack = onBack,
            status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
        ) {
            MerchantUndoBanner(state, actions.undo)
            if (state.readOnly) SettingsInlineEmpty(
                title = stringResource(R.string.merchant_management_readonly_title),
                body = stringResource(R.string.merchant_management_readonly_hint),
            )
            when {
                editors.activeCreateTool != null -> MerchantCreationTask(state, actions, editors)
                editors.selectedCatalogId != null -> MerchantObjectTask(state, actions, editors, selected)
                editors.showAllAliases -> MerchantAllAliasesTask(state, actions, editors)
                else -> MerchantDirectoryTask(state, actions, editors)
            }
        }
    }
}

@Composable
private fun merchantPageHeader(
    editors: MerchantEditors,
    selected: MerchantCatalog?,
    chrome: ManagementPageChrome,
): ManagementPageHeader {
    val (title, subtitle) = when {
        editors.activeCreateTool != null -> stringResource(
            if (editors.activeCreateTool == MerchantCreateTool.Catalog) R.string.merchant_management_tools_add_catalog
            else R.string.merchant_management_tools_add_alias,
        ) to stringResource(R.string.merchant_detail_matching_note)
        editors.selectedCatalogId != null -> (selected?.displayName ?: stringResource(R.string.merchant_detail_missing)) to
            stringResource(R.string.merchant_detail_subtitle)
        editors.showAllAliases -> stringResource(R.string.merchant_directory_all_aliases) to
            stringResource(R.string.merchant_directory_all_aliases_hint)
        else -> stringResource(R.string.merchant_aliases_page_title) to stringResource(R.string.merchant_directory_subtitle)
    }
    val directoryTitle = stringResource(R.string.merchant_catalog_section_list)
    val parent = selected?.displayName ?: stringResource(
        if (editors.showAllAliases) R.string.merchant_directory_all_aliases else R.string.merchant_catalog_section_list,
    )
    val back = if (editors.activeCreateTool != null) parent else directoryTitle
    return ManagementPageHeader(title, subtitle, if (editors.isDirectory) chrome else chrome.copy(backText = back))
}

@Composable
private fun MerchantUndoBanner(state: MerchantAliasesScreenState, actions: MerchantAliasesUndoActions) {
    state.undoableAlias?.let { undoable ->
        SettingsOpenPanel {
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.merchant_aliases_undo_deleted, undoable.alias), modifier = Modifier.weight(1f))
                TextButton(enabled = !state.busy && !state.readOnly, onClick = actions.onUndoDelete) {
                    Text(stringResource(R.string.merchant_aliases_undo_button))
                }
            }
        }
    }
}

@Composable
internal fun MerchantAliasResults(state: MerchantAliasesScreenState, actions: MerchantAliasesScreenActions, editors: MerchantEditors) {
    if (state.aliasesLoadFailed) {
        SettingsInlineEmpty(title = stringResource(R.string.merchant_alias_load_failed),
            body = stringResource(R.string.merchant_aliases_reload_hint))
        TextButton(enabled = !state.busy, onClick = actions.onReloadAliases) {
            Text(stringResource(R.string.merchant_aliases_reload_button))
        }
    } else MerchantAliasListSection(state.aliases, state.readOnly, state.busy, actions.alias.onToggle) {
        actions.onStartEditing()
        editors.deletingAlias = it
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


internal class MerchantEditors {
    var selectedCatalogId by mutableStateOf<String?>(null)
    var showAllAliases by mutableStateOf(false)
    var search by mutableStateOf("")
    var status by mutableStateOf("all")
    val isDirectory get() = selectedCatalogId == null && !showAllAliases && activeCreateTool == null
    val pageKey get() = activeCreateTool?.name ?: selectedCatalogId?.let { "merchant:$it" } ?: if (showAllAliases) "aliases" else "directory"

    fun back() {
        if (activeCreateTool != null) activeCreateTool = null
        else { selectedCatalogId = null; showAllAliases = false }
    }

    fun openCreation(tool: MerchantCreateTool) {
        activeCreateTool = tool
        catalogMessage = null
        aliasMessage = null
    }

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

internal enum class MerchantCreateTool { Catalog, Alias }

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
    AppAdaptiveContentActionRow(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        style = AppAdaptiveContentActionStyle(compactAction = true),
        content = { MerchantAliasRowText(alias) },
    ) { actionModifier ->
        Row(modifier = actionModifier, verticalAlignment = Alignment.CenterVertically) {
            MerchantAliasStatus(enabled = alias.enabled)
            if (!readOnly) {
                MerchantAliasActionMenu(alias, busy, onToggleAlias, onDeleteAlias)
            }
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
        )
        Text(
            text = stringResource(R.string.merchant_aliases_card_canonical, alias.canonicalMerchant),
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.bodyMedium,
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
