package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FolderShared
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.LedgerSwitcherViewModel
import com.valentinilk.shimmer.shimmer

private const val LEDGER_NAME_MAX = 60

/**
 * v0.4-alpha1 minimum-viable ledger management surface.
 *
 * Renders the list of ledgers the current account belongs to, lets the user
 * switch between them (rotating the session token server-side) and create a
 * new ledger. Ownership is decided server-side; this screen never trusts
 * client-supplied roles for authorization.
 *
 * ViewModel-driven as of 2026-05 (was Repository-injected — that broke the
 * Screen → ViewModel → Repository → IO layer rule).
 */
@Composable
fun LedgerSwitcherScreen(
    viewModel: LedgerSwitcherViewModel,
    activeLedgerId: String?,
    onBack: () -> Unit,
    onSwitched: () -> Unit,
) {
    val state by viewModel.uiState.collectAsState()
    var newLedgerName by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    SettingsPageFrame(
        title = stringResource(R.string.ledger_switcher_page_title),
        subtitle = stringResource(R.string.ledger_switcher_page_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = MessageTone.Neutral) },
    ) {
        SettingsSection(
            title = stringResource(R.string.ledger_switcher_section_joined),
            icon = Icons.Filled.FolderShared,
        ) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                ) {
                    if (state.ledgers.isEmpty() && state.loading) {
                        Column(modifier = Modifier.shimmer()) {
                            repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
                        }
                    } else if (state.ledgers.isEmpty()) {
                        Text(
                            text = stringResource(R.string.ledger_switcher_ledgers_empty),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    state.ledgers.forEach { ledger ->
                        val isActive = ledger.ledgerId == activeLedgerId
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                        ) {
                            Column(
                                modifier = Modifier.weight(1f).padding(end = AppSpacing.compactGap),
                            ) {
                                Text(
                                    text = ledger.name,
                                    style = MaterialTheme.typography.titleSmall,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                                    SettingsLedgerScopeChip(isDefault = ledger.isDefault)
                                    Spacer(Modifier.width(6.dp))
                                    SettingsRoleChip(role = ledger.role)
                                    if (isActive) {
                                        Spacer(Modifier.width(6.dp))
                                        Text(
                                            text = stringResource(R.string.ledger_switcher_row_current_badge),
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                            }
                            if (!isActive) {
                                TextButton(
                                    onClick = {
                                        if (!state.loading) {
                                            viewModel.switchTo(ledger.ledgerId, onSwitched)
                                        }
                                    },
                                ) { Text(stringResource(R.string.ledger_switcher_row_switch_button)) }
                            }
                        }
                    }
                    OutlinedButton(
                        onClick = { viewModel.refresh() },
                        enabled = !state.loading,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            if (state.loading) {
                                stringResource(R.string.ledger_switcher_refresh_loading)
                            } else {
                                stringResource(R.string.ledger_switcher_refresh_button)
                            },
                        )
                    }
                }
            }
        }

        SettingsSection(
            title = stringResource(R.string.ledger_switcher_section_create),
            icon = Icons.Filled.FolderShared,
        ) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = stringResource(R.string.ledger_switcher_create_hint, LEDGER_NAME_MAX),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedTextField(
                        value = newLedgerName,
                        onValueChange = { value ->
                            // Trim hard upper bound on input to prevent oversize requests.
                            newLedgerName = value.take(LEDGER_NAME_MAX)
                        },
                        label = { Text(stringResource(R.string.ledger_switcher_field_ledger_name)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(
                        onClick = {
                            val name = newLedgerName.trim()
                            if (name.isEmpty()) {
                                viewModel.showInputError(
                                    UiText.res(R.string.ledger_switcher_message_name_required),
                                )
                                return@Button
                            }
                            viewModel.create(name) { newLedgerName = "" }
                        },
                        enabled = !state.loading,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(stringResource(R.string.ledger_switcher_create_button)) }
                }
            }
        }
    }
}
