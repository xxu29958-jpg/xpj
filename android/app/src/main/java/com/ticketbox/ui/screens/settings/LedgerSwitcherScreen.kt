package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Group
import androidx.compose.material.icons.outlined.MailOutline
import androidx.compose.material.icons.outlined.MenuBook
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.ledgerRoleLabelText
import com.ticketbox.viewmodel.LedgerListLoadState
import com.ticketbox.viewmodel.LedgerSwitcherUiState
import com.ticketbox.viewmodel.LedgerSwitcherViewModel

private const val LEDGER_NAME_MAX = 60

data class LedgerSwitcherNavigation(
    val onBack: () -> Unit,
    val onSwitched: () -> Unit,
    val onRenamed: () -> Unit,
    val onJoin: () -> Unit,
)

@Composable
fun LedgerSwitcherScreen(viewModel: LedgerSwitcherViewModel, activeLedgerId: String?, navigation: LedgerSwitcherNavigation) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { viewModel.refresh() }
    LedgerDirectoryPage(state, activeLedgerId, LedgerDirectoryActions(
        onBack = navigation.onBack, onJoin = navigation.onJoin, onRefresh = viewModel::refresh,
        onSwitch = { viewModel.switchTo(it, navigation.onSwitched) }, onRename = viewModel::beginRename,
        onCreate = { name, created -> viewModel.create(name, created) },
        onNameRequired = { viewModel.showInputError(UiText.res(R.string.ledger_switcher_message_name_required)) },
    ))
    LedgerRenameDialog(state, viewModel::changeRenameName, viewModel::dismissRename,
        onSave = { viewModel.saveRename(navigation.onRenamed) }, onRefresh = viewModel::refresh)
}

internal data class LedgerDirectoryActions(
    val onBack: () -> Unit,
    val onJoin: () -> Unit,
    val onRefresh: () -> Unit,
    val onSwitch: (String) -> Unit,
    val onRename: (LedgerSummary) -> Unit,
    val onCreate: (String, () -> Unit) -> Unit,
    val onNameRequired: () -> Unit,
)

@Composable
internal fun LedgerDirectoryPage(state: LedgerSwitcherUiState, activeLedgerId: String?, actions: LedgerDirectoryActions) {
    var name by rememberSaveable { mutableStateOf("") }
    var showManagement by rememberSaveable { mutableStateOf(false) }
    LedgerSettingsPage(
        header = ManagementPageHeader(stringResource(R.string.ledger_switcher_page_title),
            stringResource(R.string.ledger_switcher_page_subtitle)), onBack = actions.onBack,
        action = SettingsPageAction(stringResource(R.string.ledger_switcher_create_button), !state.loading) {
            val trimmed = name.trim()
            if (trimmed.isEmpty()) actions.onNameRequired() else actions.onCreate(trimmed) { name = "" }
        },
    ) {
        AppStatusBanner(message = state.message, tone = state.messageTone)
        LedgerDirectoryRows(state, activeLedgerId, onSwitch = actions.onSwitch,
            onShowCurrent = { showManagement = !showManagement })
        AppTextInput(
            state = AppTextInputState(label = stringResource(R.string.ledger_switcher_field_new_ledger_name), value = name,
                placeholder = stringResource(R.string.ledger_switcher_name_placeholder), enabled = !state.loading),
            actions = AppTextInputActions(onValueChange = { name = it.take(LEDGER_NAME_MAX) }),
            decorations = AppTextInputDecorations(roundedSurface = true,
                trailingContent = { Icon(Icons.Outlined.Edit, contentDescription = null) }),
        )
        SettingsDataRow(stringResource(R.string.join_family_ledger_page_title),
            stringResource(R.string.ledger_switcher_join_hint), Icons.Outlined.MailOutline,
            SettingsDataAction(""), onClick = if (state.loading) null else actions.onJoin)
        SettingsEntryRow(stringResource(R.string.ledger_switcher_manage), stringResource(R.string.ledger_switcher_manage_hint),
            R.drawable.ic_lucide_sliders_horizontal, onClick = { showManagement = !showManagement }, expanded = showManagement)
        if (showManagement || state.listLoadState == LedgerListLoadState.Failed) LedgerManagement(state, activeLedgerId, actions)
    }
}

@Composable
private fun LedgerDirectoryRows(state: LedgerSwitcherUiState, activeLedgerId: String?, onSwitch: (String) -> Unit, onShowCurrent: () -> Unit) {
    if (state.ledgers.isEmpty()) {
        SettingsListStateSlot(
            loading = state.listLoadState != LedgerListLoadState.Failed && (state.loading || state.listLoadState != LedgerListLoadState.Loaded),
            hasData = false,
            copy = SettingsStateSlotCopy(
                loadingTitle = stringResource(R.string.ledger_switcher_loading_title), loadingBody = stringResource(R.string.ledger_switcher_loading_body),
                emptyText = stringResource(R.string.ledger_switcher_ledgers_empty), emptyTitle = stringResource(R.string.ledger_switcher_empty_title),
                emptyBody = stringResource(R.string.ledger_switcher_ledgers_empty)),
            message = state.message.takeIf { state.listLoadState == LedgerListLoadState.Failed }
                ?.let { SettingsStateSlotMessage(it, state.messageTone) },
        )
    } else Column {
        state.ledgers.forEach { ledger ->
            val active = ledger.ledgerId == activeLedgerId
            SettingsDataRow(ledger.name, ledgerRoleLabelText(ledger.role),
                if (ledger.isDefault) Icons.Outlined.MenuBook else Icons.Outlined.Group,
                SettingsDataAction(stringResource(if (active) R.string.ledger_switcher_row_current_badge
                    else R.string.ledger_switcher_row_switch_button), if (active) true else null),
                onClick = if (state.loading) null else { { if (active) onShowCurrent() else onSwitch(ledger.ledgerId) } })
        }
    }
}

@Composable
private fun LedgerManagement(state: LedgerSwitcherUiState, activeLedgerId: String?, actions: LedgerDirectoryActions) {
    SettingsSection(title = stringResource(R.string.ledger_switcher_section_overview)) {
        Text(stringResource(R.string.ledger_switcher_overview_count_value, state.ledgers.size), style = MaterialTheme.typography.titleMedium)
        state.ledgers.forEach { ledger ->
            ManagedLedgerRow(ledger, ledger.ledgerId == activeLedgerId, state.loading, actions.onRename)
        }
        TextButton(enabled = !state.loading, onClick = actions.onRefresh) {
            Text(stringResource(if (state.loading) R.string.ledger_switcher_refresh_loading else R.string.ledger_switcher_refresh_button))
        }
    }
}

@Composable
private fun ManagedLedgerRow(ledger: LedgerSummary, active: Boolean, loading: Boolean, onRename: (LedgerSummary) -> Unit) {
    Column {
        Text(ledger.name, style = MaterialTheme.typography.titleSmall)
        Text(ledgerRoleLabelText(ledger.role), style = MaterialTheme.typography.bodySmall)
        SettingsLedgerScopeChip(isDefault = ledger.isDefault)
        if (active) SettingsCurrentChip(stringResource(R.string.ledger_switcher_row_current_badge))
        if (ledger.role == "owner") TextButton(enabled = !loading, onClick = { onRename(ledger) }) {
            Text(stringResource(R.string.ledger_name_edit))
        }
    }
}
