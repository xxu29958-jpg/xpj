package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun MerchantDirectoryTask(state: MerchantAliasesScreenState, actions: MerchantAliasesScreenActions, editors: MerchantEditors) {
    MerchantDirectorySearch(editors)
    val term = editors.search.trim()
    val matchingKeys = state.aliases.filter {
        it.alias.contains(term, ignoreCase = true) || it.canonicalMerchant.contains(term, ignoreCase = true)
    }.map { it.canonicalKey }.toSet()
    val visible = state.catalog.filter {
        (editors.status == "all" || it.status == editors.status) &&
            (it.displayName.contains(term, ignoreCase = true) || it.merchantKey in matchingKeys)
    }
    if (visible.isEmpty()) SettingsInlineEmpty(
        title = stringResource(if (state.catalog.isEmpty()) R.string.merchant_catalog_list_empty_title else R.string.merchant_directory_no_match),
        body = stringResource(if (state.catalog.isEmpty()) R.string.merchant_catalog_list_empty else R.string.merchant_directory_no_match_hint),
    )
    visible.forEach { item ->
        SettingsEntryRow(item.displayName, merchantCatalogSummary(item, state.catalog), R.drawable.ic_lucide_store,
            onClick = { editors.selectedCatalogId = item.publicId })
    }
    SettingsSection(title = stringResource(R.string.merchant_management_section_tools)) {
        SettingsEntryRow(stringResource(R.string.merchant_directory_all_aliases),
            stringResource(R.string.merchant_directory_all_aliases_hint), R.drawable.ic_lucide_tag,
            onClick = { editors.showAllAliases = true })
        MerchantMatchingNote()
    }
    if (!state.readOnly) AppPrimaryButton(
        text = stringResource(R.string.merchant_management_tools_add_catalog), enabled = !state.busy,
        modifier = Modifier.fillMaxWidth(),
        onClick = { actions.onStartEditing(); editors.openCreation(MerchantCreateTool.Catalog) },
    )
}

@Composable
private fun MerchantDirectorySearch(editors: MerchantEditors) {
    SettingsDialogTextInput(state = SettingsTextInputState(label = stringResource(R.string.merchant_directory_search), value = editors.search),
        onValueChange = { editors.search = it })
    FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        listOf("all" to R.string.merchant_directory_all, "active" to R.string.merchant_catalog_card_status_visible,
            "hidden" to R.string.merchant_catalog_card_status_hidden, "merged" to R.string.merchant_catalog_card_status_merged).forEach { (key, label) ->
            AppFilterChip(stringResource(label), editors.status == key, { editors.status = key })
        }
    }
}

@Composable
internal fun MerchantObjectTask(
    state: MerchantAliasesScreenState,
    actions: MerchantAliasesScreenActions,
    editors: MerchantEditors,
    item: MerchantCatalog?,
) {
    if (item == null) {
        SettingsInlineEmpty(stringResource(R.string.merchant_detail_missing), stringResource(R.string.merchant_detail_missing_hint))
        return
    }
    Text(merchantCatalogSummary(item, state.catalog), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
    if (item.isMerged) {
        val target = state.catalog.find { it.publicId == item.mergedIntoPublicId }
        if (target != null) SettingsEntryRow(target.displayName, stringResource(R.string.merchant_catalog_card_status_merged),
            R.drawable.ic_lucide_git_branch, onClick = { editors.selectedCatalogId = target.publicId })
    }
    MerchantAliasResults(state.copy(aliases = state.aliases.filter { it.canonicalKey == item.merchantKey }), actions, editors)
    MerchantMatchingNote()
    if (!state.readOnly && !item.isMerged) {
        MerchantAddAlias(state, actions, editors, item)
        SettingsDetailRow(stringResource(R.string.merchant_detail_identity), stringResource(R.string.merchant_detail_identity_hint),
            R.drawable.ic_lucide_store) {
            MerchantObjectActions(item, state, actions, editors)
        }
    }
}

@Composable
internal fun MerchantAllAliasesTask(state: MerchantAliasesScreenState, actions: MerchantAliasesScreenActions, editors: MerchantEditors) {
    MerchantAliasResults(state, actions, editors)
    MerchantMatchingNote()
    if (!state.readOnly) MerchantAddAlias(state, actions, editors, null)
}

@Composable
private fun MerchantAddAlias(
    state: MerchantAliasesScreenState,
    actions: MerchantAliasesScreenActions,
    editors: MerchantEditors,
    item: MerchantCatalog?,
) {
    AppPrimaryButton(text = stringResource(R.string.merchant_management_tools_add_alias), enabled = !state.busy,
        modifier = Modifier.fillMaxWidth(), onClick = {
            actions.onStartEditing()
            // Reopening a different task must not replace an independently started alias draft.
            if (state.creation.draft(com.ticketbox.data.repository.MerchantCreationKind.Alias) == null && item != null)
                actions.creation.onEdit(com.ticketbox.data.repository.MerchantCreationKind.Alias, "", item.displayName, "")
            editors.openCreation(MerchantCreateTool.Alias)
        })
}

@Composable
private fun MerchantObjectActions(item: MerchantCatalog, state: MerchantAliasesScreenState, actions: MerchantAliasesScreenActions, editors: MerchantEditors) {
    AppActionRow(
        primary = AppAction(stringResource(R.string.merchant_catalog_card_action_rename), enabled = !state.busy,
            onClick = { actions.onStartEditing(); editors.catalogDialogs.openRename(item) }),
        secondary = AppAction(stringResource(R.string.merchant_catalog_card_action_merge),
            enabled = !state.busy && state.catalog.any { it.isActive && it.publicId != item.publicId },
            onClick = { actions.onStartEditing(); editors.catalogDialogs.openMerge(item) }),
    )
    AppActionRow(
        primary = AppAction(stringResource(if (item.isActive) R.string.merchant_catalog_card_action_hide else R.string.merchant_catalog_card_action_show),
            enabled = !state.busy, onClick = { actions.catalog.onToggle(item) }),
        secondary = AppAction(stringResource(R.string.merchant_catalog_card_action_delete), enabled = !state.busy,
            onClick = { actions.onStartEditing(); editors.deletingCatalog = item }),
    )
    Text(stringResource(R.string.merchant_catalog_delete_dialog_text, item.displayName), style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun MerchantMatchingNote() {
    Text(stringResource(R.string.merchant_detail_matching_note), style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun merchantCatalogSummary(item: MerchantCatalog, catalog: List<MerchantCatalog>): String {
    val target = catalog.find { it.publicId == item.mergedIntoPublicId }
    if (item.isMerged && target != null) return stringResource(R.string.merchant_catalog_card_merged_into, target.displayName)
    val label = when {
        item.isMerged -> R.string.merchant_catalog_card_status_merged
        item.isActive -> R.string.merchant_catalog_card_status_visible
        else -> R.string.merchant_catalog_card_status_hidden
    }
    return stringResource(R.string.merchant_catalog_usage, item.usageCount, stringResource(label))
}
