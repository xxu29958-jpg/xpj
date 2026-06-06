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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import com.ticketbox.R
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import kotlinx.coroutines.delay

@Composable
fun MerchantAliasesScreen(
    aliases: List<MerchantAlias>,
    busy: Boolean,
    readOnly: Boolean,
    message: UiText?,
    onBack: () -> Unit,
    onCreateAlias: (String, String) -> Unit,
    onToggleAlias: (MerchantAlias) -> Unit,
    onDeleteAlias: (MerchantAlias) -> Unit,
    undoableAlias: MerchantAlias? = null,
    onUndoDelete: () -> Unit = {},
    onDismissUndo: () -> Unit = {},
) {
    var canonicalMerchant by remember { mutableStateOf("") }
    var aliasText by remember { mutableStateOf("") }
    var localMessage by remember { mutableStateOf<String?>(null) }
    var deletingAlias by remember { mutableStateOf<MerchantAlias?>(null) }
    // ADR-0044: stringResource is @Composable-only, but this validation message is
    // assigned inside a non-composable onClick lambda below. Hoist the resolved string here.
    val createValidationMessage = stringResource(R.string.merchant_aliases_create_validation)

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
        subtitle = merchantAliasSummary(aliases),
        onBack = onBack,
    ) {
        // ADR-0038 undo: a soft-deleted alias is recoverable for a 5s window.
        // Online-only (only shown after a synced delete); auto-dismisses.
        undoableAlias?.let { undoable ->
            LaunchedEffect(undoable.publicId) {
                delay(5000)
                onDismissUndo()
            }
            AppGlassCard(containerAlpha = 0.98f) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(AppSpacing.compactGap),
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

        if (!readOnly) {
            SettingsSection(title = stringResource(R.string.merchant_aliases_section_create), icon = Icons.Filled.Tune) {
                AppGlassCard(containerAlpha = 0.96f) {
                    Column(
                        modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                    ) {
                        OutlinedTextField(
                            value = canonicalMerchant,
                            onValueChange = { canonicalMerchant = it },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text(stringResource(R.string.merchant_aliases_canonical_label)) },
                            placeholder = { Text(stringResource(R.string.merchant_aliases_canonical_placeholder)) },
                            singleLine = true,
                        )
                        OutlinedTextField(
                            value = aliasText,
                            onValueChange = { aliasText = it },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text(stringResource(R.string.merchant_aliases_alias_label)) },
                            placeholder = { Text("Starbucks") },
                            singleLine = true,
                        )
                        Button(
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !busy,
                            onClick = {
                                if (canonicalMerchant.isBlank() || aliasText.isBlank()) {
                                    localMessage = createValidationMessage
                                    return@Button
                                }
                                localMessage = null
                                onCreateAlias(canonicalMerchant, aliasText)
                                canonicalMerchant = ""
                                aliasText = ""
                            },
                        ) {
                            Text(
                                if (busy) {
                                    stringResource(R.string.merchant_aliases_create_busy)
                                } else {
                                    stringResource(R.string.merchant_aliases_create_button)
                                },
                            )
                        }
                        localMessage?.let {
                            Text(it, color = MaterialTheme.colorScheme.secondary)
                        }
                    }
                }
            }
        } else {
            Text(
                text = stringResource(R.string.common_readonly_ledger),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        SettingsSection(title = stringResource(R.string.merchant_aliases_section_list), icon = Icons.Filled.Tune) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                if (aliases.isEmpty()) {
                    Text(
                        text = stringResource(R.string.merchant_aliases_list_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    aliases.forEach { item ->
                        MerchantAliasCard(
                            alias = item,
                            readOnly = readOnly,
                            busy = busy,
                            onToggleAlias = { onToggleAlias(item) },
                            onDeleteAlias = { deletingAlias = item },
                        )
                    }
                }
            }
        }

        message?.asString()?.takeIf { it.isNotBlank() }?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
    }
}

@Composable
private fun MerchantAliasCard(
    alias: MerchantAlias,
    readOnly: Boolean,
    busy: Boolean,
    onToggleAlias: () -> Unit,
    onDeleteAlias: () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.98f) {
        Column(modifier = Modifier.padding(AppSpacing.compactGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                    Text(
                        text = alias.alias,
                        style = MaterialTheme.typography.titleSmall,
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
                }
                Spacer(Modifier.width(AppSpacing.compactGap))
                Text(
                    text = if (alias.enabled) {
                        stringResource(R.string.merchant_aliases_card_status_enabled)
                    } else {
                        stringResource(R.string.merchant_aliases_card_status_disabled)
                    },
                    color = if (alias.enabled) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    fontWeight = AppTextHierarchy.body.weight,
                )
            }
            Text(
                text = "${alias.aliasKey} -> ${alias.canonicalKey}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (!readOnly) {
                Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onToggleAlias,
                    ) {
                        Text(
                            if (alias.enabled) {
                                stringResource(R.string.merchant_aliases_card_action_disable)
                            } else {
                                stringResource(R.string.merchant_aliases_card_action_enable)
                            },
                        )
                    }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onDeleteAlias,
                    ) {
                        Text(stringResource(R.string.merchant_aliases_card_action_delete))
                    }
                }
            }
        }
    }
}

@Composable
private fun merchantAliasSummary(aliases: List<MerchantAlias>): String {
    val enabled = aliases.count { it.enabled }
    return if (aliases.isEmpty()) {
        stringResource(R.string.merchant_aliases_summary_empty)
    } else {
        stringResource(R.string.merchant_aliases_summary_count, enabled, aliases.size)
    }
}
