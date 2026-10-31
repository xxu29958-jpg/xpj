package com.ticketbox.ui.navigation

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ManualEntryTemplateStore
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.screens.LedgerScreenActions
import com.ticketbox.viewmodel.LedgerUiState
import kotlinx.coroutines.launch
import java.util.UUID

@Composable
internal fun ManualTemplateHost(
    binding: LogicalSessionBinding,
    currentBinding: () -> LogicalSessionBinding?,
    launchAction: LaunchActionState,
    state: LedgerUiState,
    actions: LedgerScreenActions,
) {
    var open by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(launchAction.pending is LaunchAction.OpenTemplates) {
        if (launchAction.pending is LaunchAction.OpenTemplates) {
            launchAction.consume(LaunchAction.OpenTemplates)
            open = true
        }
    }
    if (open) ManualTemplatePanel(binding, currentBinding, state, actions) { open = false }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ManualTemplatePanel(
    binding: LogicalSessionBinding, currentBinding: () -> LogicalSessionBinding?,
    state: LedgerUiState, actions: LedgerScreenActions, onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val store = remember(binding) { ManualEntryTemplateStore(context.applicationContext, binding) }
    val controller = remember(store) { ManualTemplateController(store, binding, currentBinding, scope) }
    var editing by rememberSaveable { mutableStateOf<String?>(null) }
    var selected by rememberSaveable { mutableStateOf<String?>(null) }
    var entryKey by rememberSaveable { mutableStateOf("") }
    var homeCurrency by rememberSaveable { mutableStateOf<CurrencyCode?>(null) }
    val draftState = rememberSaveableStateHolder()
    LaunchedEffect(controller) { controller.reload() }
    LaunchedEffect(selected, editing) {
        if (selected != null || editing != null) homeCurrency = actions.onPrepareManualCreate()
    }
    LaunchedEffect(state.manualCreateResult) {
        if (selected != null && state.manualCreateResult != null) {
            onDismiss()
            actions.onManualCreateSettled()
        }
    }
    val dismiss = { if (!controller.busy && !state.creatingManual) { onDismiss(); actions.onManualCreateSettled() } }
    val panelActions = ManualTemplatePanelActions(
        edit = { homeCurrency = null; editing = it },
        select = { homeCurrency = null; entryKey = UUID.randomUUID().toString(); selected = it },
        save = { entry -> controller.change({ store.save(entry) }) { editing = null } },
        delete = { id -> controller.change({ store.remove(id) }) { editing = null } },
        dismiss = dismiss,
        reload = { scope.launch { controller.reload() } },
        prepareCurrency = { scope.launch { homeCurrency = actions.onPrepareManualCreate() } },
    )
    val entryActions = actions.copy(onManualCreate = { if (currentBinding() == binding) actions.onManualCreate(it) })
    ModalBottomSheet(onDismissRequest = dismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        draftState.SaveableStateProvider(entryKey.ifEmpty { "template-list" }) {
            ManualTemplatePanelContent(ManualTemplatePanelState(controller.entries, controller.error, controller.busy,
                editing, selected, entryKey, homeCurrency), state, entryActions, panelActions)
        }
    }
}
