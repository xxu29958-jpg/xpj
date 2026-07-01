package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal data class MerchantCatalogListActions(
    val onRename: (MerchantCatalog) -> Unit,
    val onToggle: (MerchantCatalog) -> Unit,
    val onMerge: (MerchantCatalog) -> Unit,
    val onDelete: (MerchantCatalog) -> Unit,
)

@Composable
internal fun MerchantCatalogListSection(
    catalog: List<MerchantCatalog>,
    readOnly: Boolean,
    busy: Boolean,
    actions: MerchantCatalogListActions,
) {
    SettingsSection(title = stringResource(R.string.merchant_catalog_section_list), icon = Icons.Filled.Tune) {
        if (catalog.isEmpty()) {
            SettingsInlineEmpty(
                title = stringResource(R.string.merchant_catalog_list_empty_title),
                body = stringResource(R.string.merchant_catalog_list_empty),
            )
            return@SettingsSection
        }
        val catalogById = catalog.associateBy { it.publicId }
        val activeCatalogCount = catalog.count { it.isActive }
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
            catalog.forEachIndexed { index, item ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
                }
                MerchantCatalogRow(
                    state = MerchantCatalogRowState(
                        catalog = item,
                        mergedTargetName = item.mergedIntoPublicId?.let { id -> catalogById[id]?.displayName ?: id },
                        readOnly = readOnly,
                        busy = busy,
                        canMerge = activeCatalogCount > 0 && !item.isMerged && !(item.isActive && activeCatalogCount == 1),
                    ),
                    actions = actions,
                )
            }
        }
    }
}

private data class MerchantCatalogRowState(
    val catalog: MerchantCatalog,
    val mergedTargetName: String?,
    val readOnly: Boolean,
    val busy: Boolean,
    val canMerge: Boolean,
)

@Composable
private fun MerchantCatalogRow(
    state: MerchantCatalogRowState,
    actions: MerchantCatalogListActions,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = state.catalog.displayName,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = if (state.catalog.isMerged && state.mergedTargetName != null) {
                    stringResource(R.string.merchant_catalog_card_merged_into, state.mergedTargetName)
                } else {
                    stringResource(
                        R.string.merchant_catalog_card_key_usage,
                        state.catalog.merchantKey,
                        state.catalog.usageCount,
                    )
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            text = merchantCatalogStatusText(state.catalog),
            color = if (state.catalog.isActive) {
                MaterialTheme.colorScheme.primary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            style = MaterialTheme.typography.labelMedium,
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
        )
        if (!state.readOnly && !state.catalog.isMerged) {
            MerchantCatalogActionMenu(state, actions)
        }
    }
}

@Composable
private fun MerchantCatalogActionMenu(
    state: MerchantCatalogRowState,
    actions: MerchantCatalogListActions,
) {
    var expanded by remember(state.catalog.publicId) { mutableStateOf(false) }
    IconButton(
        enabled = !state.busy,
        onClick = { expanded = true },
    ) {
        Icon(
            imageVector = Icons.Filled.MoreVert,
            contentDescription = stringResource(R.string.merchant_catalog_actions_content_description),
        )
    }
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        DropdownMenuItem(
            text = { Text(stringResource(R.string.merchant_catalog_card_action_rename)) },
            onClick = {
                expanded = false
                actions.onRename(state.catalog)
            },
        )
        DropdownMenuItem(
            text = { Text(stringResource(R.string.merchant_catalog_card_action_merge)) },
            enabled = state.canMerge,
            onClick = {
                expanded = false
                actions.onMerge(state.catalog)
            },
        )
        DropdownMenuItem(
            text = {
                Text(
                    if (state.catalog.isActive) {
                        stringResource(R.string.merchant_catalog_card_action_hide)
                    } else {
                        stringResource(R.string.merchant_catalog_card_action_show)
                    },
                )
            },
            onClick = {
                expanded = false
                actions.onToggle(state.catalog)
            },
        )
        DropdownMenuItem(
            text = {
                Text(
                    text = stringResource(R.string.merchant_catalog_card_action_delete),
                    color = MaterialTheme.colorScheme.error,
                )
            },
            onClick = {
                expanded = false
                actions.onDelete(state.catalog)
            },
        )
    }
}

@Composable
private fun merchantCatalogStatusText(catalog: MerchantCatalog): String =
    when {
        catalog.isMerged -> stringResource(R.string.merchant_catalog_card_status_merged)
        catalog.isActive -> stringResource(R.string.merchant_catalog_card_status_visible)
        else -> stringResource(R.string.merchant_catalog_card_status_hidden)
    }
