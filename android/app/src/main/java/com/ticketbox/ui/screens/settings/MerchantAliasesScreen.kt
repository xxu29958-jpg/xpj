package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
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
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.MerchantCatalogMergeSuggestion
import kotlinx.coroutines.delay

@Composable
fun MerchantAliasesScreen(
    catalog: List<MerchantCatalog>,
    aliases: List<MerchantAlias>,
    busy: Boolean,
    readOnly: Boolean,
    message: UiText?,
    onBack: () -> Unit,
    onCreateCatalog: (String) -> Unit,
    onRenameCatalog: (MerchantCatalog, String) -> Unit,
    onToggleCatalog: (MerchantCatalog) -> Unit,
    onMergeCatalog: (MerchantCatalog, MerchantCatalog, MerchantCatalogAliasPolicy) -> Unit,
    onDeleteCatalog: (MerchantCatalog) -> Unit,
    onCreateAlias: (String, String) -> Unit,
    onToggleAlias: (MerchantAlias) -> Unit,
    onDeleteAlias: (MerchantAlias) -> Unit,
    undoableAlias: MerchantAlias? = null,
    mergeSuggestion: MerchantCatalogMergeSuggestion? = null,
    onDismissMergeSuggestion: () -> Unit = {},
    onUndoDelete: () -> Unit = {},
    onDismissUndo: () -> Unit = {},
) {
    var catalogName by remember { mutableStateOf("") }
    var canonicalMerchant by remember { mutableStateOf("") }
    var aliasText by remember { mutableStateOf("") }
    var catalogMessage by remember { mutableStateOf<String?>(null) }
    var aliasMessage by remember { mutableStateOf<String?>(null) }
    var activeCreateTool by remember { mutableStateOf<MerchantCreateTool?>(null) }
    val catalogDialogController = rememberMerchantCatalogDialogController()
    var deletingCatalog by remember { mutableStateOf<MerchantCatalog?>(null) }
    var deletingAlias by remember { mutableStateOf<MerchantAlias?>(null) }
    // Resolve strings before non-composable click handlers need them.
    val catalogValidationMessage = stringResource(R.string.merchant_catalog_create_validation)
    val createValidationMessage = stringResource(R.string.merchant_aliases_create_validation)

    MerchantCatalogDialogHost(
        controller = catalogDialogController,
        catalog = catalog,
        busy = busy,
        mergeSuggestion = mergeSuggestion,
        actions = MerchantCatalogDialogHostActions(
            onRename = onRenameCatalog,
            onMerge = onMergeCatalog,
            onDismissSuggestion = onDismissMergeSuggestion,
        ),
    )

    deletingCatalog?.let { item ->
        AlertDialog(
            onDismissRequest = { deletingCatalog = null },
            title = { Text(stringResource(R.string.merchant_catalog_delete_dialog_title)) },
            text = {
                Text(
                    stringResource(
                        R.string.merchant_catalog_delete_dialog_text,
                        item.displayName,
                    ),
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        deletingCatalog = null
                        onDeleteCatalog(item)
                    },
                ) {
                    Text(stringResource(R.string.merchant_catalog_delete_dialog_confirm), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deletingCatalog = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    deletingAlias?.let { item ->
        AlertDialog(
            onDismissRequest = { deletingAlias = null },
            title = { Text(stringResource(R.string.merchant_aliases_delete_dialog_title)) },
            text = {
                Text(
                    stringResource(
                        R.string.merchant_aliases_delete_dialog_text,
                        item.alias,
                        item.canonicalMerchant,
                    ),
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        deletingAlias = null
                        onDeleteAlias(item)
                    },
                ) {
                    Text(stringResource(R.string.merchant_aliases_delete_dialog_confirm), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deletingAlias = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.merchant_aliases_page_title),
        subtitle = merchantAliasSummary(catalog, aliases),
        onBack = onBack,
        status = { AppStatusBanner(message = message, tone = MessageTone.Neutral) },
    ) {
        // Online deletes expose a short undo window.
        undoableAlias?.let { undoable ->
            LaunchedEffect(undoable.publicId) {
                delay(5000)
                onDismissUndo()
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
                    TextButton(onClick = onUndoDelete) { Text(stringResource(R.string.merchant_aliases_undo_button)) }
                }
            }
        }

        if (readOnly) {
            SettingsInlineEmpty(
                title = stringResource(R.string.merchant_management_readonly_title),
                body = stringResource(R.string.merchant_management_readonly_hint),
            )
        }
        MerchantManagementOverviewSection(catalog = catalog, aliases = aliases)

        MerchantCatalogListSection(
            catalog = catalog,
            readOnly = readOnly,
            busy = busy,
            actions = MerchantCatalogListActions(
                onRename = catalogDialogController::openRename,
                onToggle = onToggleCatalog,
                onMerge = catalogDialogController::openMerge,
                onDelete = { deletingCatalog = it },
            ),
        )

        MerchantAliasListSection(
            aliases = aliases,
            readOnly = readOnly,
            busy = busy,
            onToggleAlias = onToggleAlias,
            onDeleteAlias = { deletingAlias = it },
        )

        if (!readOnly) {
            MerchantManagementToolsSection(
                state = MerchantManagementToolState(
                    activeTool = activeCreateTool,
                    catalogName = catalogName,
                    aliasDraft = MerchantAliasDraft(
                        canonicalMerchant = canonicalMerchant,
                        aliasText = aliasText,
                    ),
                    busy = busy,
                    catalogMessage = catalogMessage,
                    aliasMessage = aliasMessage,
                ),
                actions = MerchantManagementToolActions(
                    onStartCatalog = {
                        activeCreateTool = MerchantCreateTool.Catalog
                        catalogMessage = null
                        aliasMessage = null
                    },
                    onStartAlias = {
                        activeCreateTool = MerchantCreateTool.Alias
                        catalogMessage = null
                        aliasMessage = null
                    },
                    onCatalogNameChange = { catalogName = it },
                    onAliasDraftChange = {
                        canonicalMerchant = it.canonicalMerchant
                        aliasText = it.aliasText
                    },
                    onSubmitCatalog = {
                        if (catalogName.isBlank()) {
                            catalogMessage = catalogValidationMessage
                        } else {
                            catalogMessage = null
                            onCreateCatalog(catalogName)
                            catalogName = ""
                            activeCreateTool = null
                        }
                    },
                    onSubmitAlias = {
                        if (canonicalMerchant.isBlank() || aliasText.isBlank()) {
                            aliasMessage = createValidationMessage
                        } else {
                            aliasMessage = null
                            onCreateAlias(canonicalMerchant, aliasText)
                            canonicalMerchant = ""
                            aliasText = ""
                            activeCreateTool = null
                        }
                    },
                    onCancel = {
                        activeCreateTool = null
                        catalogMessage = null
                        aliasMessage = null
                    },
                ),
            )
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
    SettingsSection(title = stringResource(R.string.merchant_management_section_tools), icon = Icons.Filled.Tune) {
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
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(enabled = !state.busy, onClick = actions.onStartCatalog) {
                        Text(stringResource(R.string.merchant_management_tools_add_catalog))
                    }
                    TextButton(enabled = !state.busy, onClick = actions.onStartAlias) {
                        Text(stringResource(R.string.merchant_management_tools_add_alias))
                    }
                }
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
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(modifier = Modifier.weight(1f), enabled = !state.busy, onClick = actions.onSubmit) {
                Text(
                    text = if (state.busy) {
                        stringResource(R.string.merchant_catalog_create_busy)
                    } else {
                        stringResource(R.string.merchant_catalog_create_button)
                    },
                )
            }
            TextButton(enabled = !state.busy, onClick = actions.onCancel) {
                Text(stringResource(R.string.common_cancel))
            }
        }
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
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(modifier = Modifier.weight(1f), enabled = !state.busy, onClick = actions.onSubmit) {
                Text(
                    text = if (state.busy) {
                        stringResource(R.string.merchant_aliases_create_busy)
                    } else {
                        stringResource(R.string.merchant_aliases_create_button)
                    },
                )
            }
            TextButton(enabled = !state.busy, onClick = actions.onCancel) {
                Text(stringResource(R.string.common_cancel))
            }
        }
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
    SettingsSection(title = stringResource(R.string.merchant_aliases_section_list), icon = Icons.Filled.Tune) {
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
