package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.ui.components.AppGlassCard
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
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            if (catalog.isEmpty()) {
                Text(
                    text = stringResource(R.string.merchant_catalog_list_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                val catalogById = catalog.associateBy { it.publicId }
                val activeCatalogCount = catalog.count { it.isActive }
                catalog.forEach { item ->
                    MerchantCatalogCard(
                        state = MerchantCatalogCardState(
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
}

private data class MerchantCatalogCardState(
    val catalog: MerchantCatalog,
    val mergedTargetName: String?,
    val readOnly: Boolean,
    val busy: Boolean,
    val canMerge: Boolean,
)

@Composable
private fun MerchantCatalogCard(
    state: MerchantCatalogCardState,
    actions: MerchantCatalogListActions,
) {
    AppGlassCard(containerAlpha = 0.98f) {
        Column(modifier = Modifier.padding(AppSpacing.compactGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            MerchantCatalogCardHeader(state.catalog, state.mergedTargetName)
            if (!state.readOnly && !state.catalog.isMerged) {
                MerchantCatalogCardActions(state, actions)
            }
        }
    }
}

@Composable
private fun MerchantCatalogCardHeader(catalog: MerchantCatalog, mergedTargetName: String?) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(
                text = catalog.displayName,
                style = MaterialTheme.typography.titleSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = if (catalog.isMerged && mergedTargetName != null) {
                    stringResource(R.string.merchant_catalog_card_merged_into, mergedTargetName)
                } else {
                    stringResource(
                        R.string.merchant_catalog_card_key_usage,
                        catalog.merchantKey,
                        catalog.usageCount,
                    )
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(AppSpacing.compactGap))
        Text(
            text = merchantCatalogStatusText(catalog),
            color = if (catalog.isActive) {
                MaterialTheme.colorScheme.primary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            fontWeight = AppTextHierarchy.body.weight,
        )
    }
}

@Composable
private fun MerchantCatalogCardActions(
    state: MerchantCatalogCardState,
    actions: MerchantCatalogListActions,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            OutlinedButton(
                modifier = Modifier.weight(1f),
                enabled = !state.busy,
                onClick = { actions.onRename(state.catalog) },
            ) {
                Text(stringResource(R.string.merchant_catalog_card_action_rename))
            }
            OutlinedButton(
                modifier = Modifier.weight(1f),
                enabled = !state.busy && state.canMerge,
                onClick = { actions.onMerge(state.catalog) },
            ) {
                Text(stringResource(R.string.merchant_catalog_card_action_merge))
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            OutlinedButton(
                modifier = Modifier.weight(1f),
                enabled = !state.busy,
                onClick = { actions.onToggle(state.catalog) },
            ) {
                Text(
                    if (state.catalog.isActive) {
                        stringResource(R.string.merchant_catalog_card_action_hide)
                    } else {
                        stringResource(R.string.merchant_catalog_card_action_show)
                    },
                )
            }
            OutlinedButton(
                modifier = Modifier.weight(1f),
                enabled = !state.busy,
                onClick = { actions.onDelete(state.catalog) },
            ) {
                Text(stringResource(R.string.merchant_catalog_card_action_delete))
            }
        }
    }
}

@Composable
private fun merchantCatalogStatusText(catalog: MerchantCatalog): String =
    when {
        catalog.isMerged -> stringResource(R.string.merchant_catalog_card_status_merged)
        catalog.isActive -> stringResource(R.string.merchant_catalog_card_status_visible)
        else -> stringResource(R.string.merchant_catalog_card_status_hidden)
    }
