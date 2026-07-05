package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FolderShared
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.LedgerSwitcherViewModel

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
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var newLedgerName by remember { mutableStateOf("") }
    val summary = remember(state.ledgers, activeLedgerId) {
        ledgerSwitcherSummary(state.ledgers, activeLedgerId)
    }

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    SettingsPageFrame(
        title = stringResource(R.string.ledger_switcher_page_title),
        subtitle = stringResource(R.string.ledger_switcher_page_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = MessageTone.Neutral) },
    ) {
        LedgerSwitcherOverviewSection(summary)
        LedgerListSection(
            ledgers = state.ledgers,
            loading = state.loading,
            activeLedgerId = activeLedgerId,
            onRefresh = viewModel::refresh,
            onSwitch = { ledgerId -> viewModel.switchTo(ledgerId, onSwitched) },
        )
        LedgerCreateSection(
            name = newLedgerName,
            loading = state.loading,
            onNameChange = { value -> newLedgerName = value.take(LEDGER_NAME_MAX) },
            onCreate = {
                val name = newLedgerName.trim()
                if (name.isEmpty()) {
                    viewModel.showInputError(UiText.res(R.string.ledger_switcher_message_name_required))
                } else {
                    viewModel.create(name) { newLedgerName = "" }
                }
            },
        )
    }
}

@Composable
private fun LedgerSwitcherOverviewSection(summary: LedgerSwitcherSummary) {
    SettingsSection(
        title = stringResource(R.string.ledger_switcher_section_overview),
        icon = Icons.Filled.FolderShared,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            SettingsMetricGrid(
                metrics = listOf(
                    SettingsMetricData(
                        label = stringResource(R.string.ledger_switcher_overview_total_label),
                        value = stringResource(R.string.ledger_switcher_overview_count_value, summary.totalCount),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.ledger_switcher_overview_current_label),
                        value = summary.currentName
                            ?: stringResource(R.string.ledger_switcher_overview_current_unknown),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.ledger_switcher_overview_switchable_label),
                        value = stringResource(
                            R.string.ledger_switcher_overview_count_value,
                            summary.switchableCount,
                        ),
                    ),
                ),
            )
        }
    }
}

@Composable
private fun LedgerListSection(
    ledgers: List<LedgerSummary>,
    loading: Boolean,
    activeLedgerId: String?,
    onRefresh: () -> Unit,
    onSwitch: (String) -> Unit,
) {
    SettingsSection(
        title = stringResource(R.string.ledger_switcher_section_joined),
        icon = Icons.Filled.FolderShared,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            LedgerListContent(
                ledgers = ledgers,
                loading = loading,
                activeLedgerId = activeLedgerId,
                onSwitch = onSwitch,
            )
            QuietOutlinedButton(
                text = if (loading) {
                    stringResource(R.string.ledger_switcher_refresh_loading)
                } else {
                    stringResource(R.string.ledger_switcher_refresh_button)
                },
                leadingIcon = Icons.Filled.Refresh,
                modifier = Modifier.fillMaxWidth(),
                enabled = !loading,
                onClick = onRefresh,
            )
        }
    }
}

@Composable
private fun LedgerListContent(
    ledgers: List<LedgerSummary>,
    loading: Boolean,
    activeLedgerId: String?,
    onSwitch: (String) -> Unit,
) {
    when {
        ledgers.isEmpty() -> SettingsListStateSlot(
            loading = loading,
            hasData = false,
            copy = SettingsStateSlotCopy(
                loadingTitle = stringResource(R.string.ledger_switcher_loading_title),
                loadingBody = stringResource(R.string.ledger_switcher_loading_body),
                emptyText = stringResource(R.string.ledger_switcher_ledgers_empty),
                emptyTitle = stringResource(R.string.ledger_switcher_empty_title),
                emptyBody = stringResource(R.string.ledger_switcher_ledgers_empty),
            ),
        )

        else -> Column {
            ledgers.forEachIndexed { index, ledger ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
                }
                LedgerRow(
                    ledger = ledger,
                    isActive = ledger.ledgerId == activeLedgerId,
                    loading = loading,
                    onSwitch = onSwitch,
                )
            }
        }
    }
}

@Composable
private fun LedgerRow(
    ledger: LedgerSummary,
    isActive: Boolean,
    loading: Boolean,
    onSwitch: (String) -> Unit,
) {
    val rowModifier = Modifier
        .fillMaxWidth()
        .padding(vertical = AppSpacing.smallGap)

    if (isActive) {
        LedgerRowContent(ledger = ledger, isActive = true, modifier = rowModifier)
    } else {
        AppAdaptiveContentActionRow(
            modifier = rowModifier,
            content = {
                LedgerRowContent(ledger = ledger, isActive = false)
            },
        ) { actionModifier ->
            QuietOutlinedButton(
                text = stringResource(R.string.ledger_switcher_row_switch_button),
                modifier = actionModifier,
                enabled = !loading,
                onClick = { onSwitch(ledger.ledgerId) },
            )
        }
    }
}

@Composable
private fun LedgerRowContent(
    ledger: LedgerSummary,
    isActive: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = ledger.name,
            style = MaterialTheme.typography.titleSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        LedgerBadgeRow(ledger = ledger, isActive = isActive)
    }
}

@Composable
private fun LedgerBadgeRow(
    ledger: LedgerSummary,
    isActive: Boolean,
) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SettingsLedgerScopeChip(isDefault = ledger.isDefault)
        SettingsRoleChip(role = ledger.role)
        if (isActive) {
            SettingsCurrentChip(text = stringResource(R.string.ledger_switcher_row_current_badge))
        }
    }
}

@Composable
private fun LedgerCreateSection(
    name: String,
    loading: Boolean,
    onNameChange: (String) -> Unit,
    onCreate: () -> Unit,
) {
    SettingsSection(
        title = stringResource(R.string.ledger_switcher_section_create),
        icon = Icons.Filled.FolderShared,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(
                text = stringResource(R.string.ledger_switcher_create_hint, LEDGER_NAME_MAX),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            SettingsDialogTextInput(
                state = SettingsTextInputState(
                    label = stringResource(R.string.ledger_switcher_field_ledger_name),
                    value = name,
                    enabled = !loading,
                ),
                onValueChange = onNameChange,
            )
            AppPrimaryButton(
                text = stringResource(R.string.ledger_switcher_create_button),
                icon = Icons.Filled.Add,
                modifier = Modifier.fillMaxWidth(),
                enabled = !loading,
                onClick = onCreate,
            )
        }
    }
}

private data class LedgerSwitcherSummary(
    val totalCount: Int,
    val currentName: String?,
    val switchableCount: Int,
)

private fun ledgerSwitcherSummary(
    ledgers: List<LedgerSummary>,
    activeLedgerId: String?,
): LedgerSwitcherSummary {
    val currentLedger = ledgers.firstOrNull { it.ledgerId == activeLedgerId }
    return LedgerSwitcherSummary(
        totalCount = ledgers.size,
        currentName = currentLedger?.name,
        switchableCount = ledgers.count { it.ledgerId != activeLedgerId },
    )
}
