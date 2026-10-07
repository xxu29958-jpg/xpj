package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.design.AppSpacing

private data class MerchantAliasDraft(val canonicalMerchant: String, val aliasText: String)

@Composable
internal fun MerchantCreationTask(state: MerchantAliasesScreenState, actions: MerchantAliasesScreenActions, editors: MerchantEditors) {
    val invalidCatalog = stringResource(R.string.merchant_catalog_create_validation)
    val invalidAlias = stringResource(R.string.merchant_aliases_create_validation)
    when (editors.activeCreateTool) {
        MerchantCreateTool.Catalog -> MerchantCatalogCreateSection(
            MerchantCatalogCreateState(editors.catalogName, state.busy, editors.catalogMessage, state.readOnly),
            MerchantCatalogCreateActions(
                onCatalogNameChange = { editors.catalogName = it },
                onSubmit = {
                    if (editors.catalogName.isBlank()) editors.catalogMessage = invalidCatalog
                    else { editors.catalogMessage = null; actions.catalog.onCreate(editors.catalogName) }
                },
                onCancel = editors::back,
            ),
        )
        MerchantCreateTool.Alias -> MerchantAliasCreateSection(
            MerchantAliasCreateState(MerchantAliasDraft(editors.canonicalMerchant, editors.aliasText), state.busy, editors.aliasMessage, state.readOnly),
            MerchantAliasCreateActions(
                onDraftChange = { editors.canonicalMerchant = it.canonicalMerchant; editors.aliasText = it.aliasText },
                onSubmit = {
                    if (editors.canonicalMerchant.isBlank() || editors.aliasText.isBlank()) editors.aliasMessage = invalidAlias
                    else { editors.aliasMessage = null; actions.alias.onCreate(editors.canonicalMerchant, editors.aliasText) }
                },
                onCancel = editors::back,
            ),
        )
        null -> Unit
    }
}

private data class MerchantCatalogCreateState(
    val catalogName: String,
    val busy: Boolean,
    val message: String?,
    val readOnly: Boolean,
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
                enabled = !state.busy && !state.readOnly,
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
                enabled = !state.busy && !state.readOnly,
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
    val readOnly: Boolean,
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
                enabled = !state.busy && !state.readOnly,
            ),
            onValueChange = { actions.onDraftChange(state.draft.copy(canonicalMerchant = it)) },
        )
        SettingsDialogTextInput(
            state = SettingsTextInputState(
                label = stringResource(R.string.merchant_aliases_alias_label),
                value = state.draft.aliasText,
                placeholder = stringResource(R.string.merchant_aliases_alias_placeholder),
                enabled = !state.busy && !state.readOnly,
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
                enabled = !state.busy && !state.readOnly,
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

