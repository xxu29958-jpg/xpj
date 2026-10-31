package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.data.repository.ManualEntryTemplate
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.ui.asString
import com.ticketbox.ui.screens.LedgerScreenActions
import com.ticketbox.ui.screens.ManualExpenseSheet
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetInitials
import com.ticketbox.ui.screens.ManualExpenseSheetState
import com.ticketbox.ui.screens.ledger.ManualTemplateEditor
import com.ticketbox.ui.screens.ledger.ManualTemplateEditorActions
import com.ticketbox.viewmodel.LedgerUiState

internal data class ManualTemplatePanelState(
    val entries: List<ManualEntryTemplate>?, val error: Int?, val busy: Boolean,
    val editing: String?, val selected: String?, val entryKey: String, val currency: CurrencyCode?,
)

internal data class ManualTemplatePanelActions(
    val edit: (String?) -> Unit, val select: (String?) -> Unit,
    val save: (ManualEntryTemplate) -> Unit, val delete: (String) -> Unit,
    val dismiss: () -> Unit, val reload: () -> Unit, val prepareCurrency: () -> Unit,
)

@Composable
internal fun ManualTemplatePanelContent(
    panel: ManualTemplatePanelState, ledger: LedgerUiState, entries: LedgerScreenActions, actions: ManualTemplatePanelActions,
) {
    val chosen = panel.entries?.firstOrNull { it.id == panel.selected }
    val scroll = if (chosen == null) Modifier.verticalScroll(rememberScrollState()) else Modifier
    Column(Modifier.fillMaxWidth().then(scroll).padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        panel.error?.let { Text(stringResource(it), color = MaterialTheme.colorScheme.error) }
        when {
            panel.entries == null -> {
                if (panel.error == null) CircularProgressIndicator()
                else TextButton(onClick = actions.reload) { Text(stringResource(R.string.common_retry)) }
            }
            (panel.editing != null || chosen != null) && panel.currency == null -> {
                Text(stringResource(R.string.ledger_manual_currency_loading))
                TextButton(onClick = actions.prepareCurrency) { Text(stringResource(R.string.common_retry)) }
            }
            else -> ManualTemplatePanelBody(panel, ledger, entries, actions)
        }
        TextButton(onClick = actions.dismiss, enabled = !panel.busy && !ledger.creatingManual) { Text(stringResource(R.string.widget_cancel)) }
    }
}

@Composable
private fun ManualTemplatePanelBody(
    panel: ManualTemplatePanelState, ledger: LedgerUiState, entries: LedgerScreenActions, actions: ManualTemplatePanelActions,
) {
    val chosen = panel.entries?.firstOrNull { it.id == panel.selected }
    when {
        panel.editing != null -> key(panel.editing) {
            val original = panel.entries?.firstOrNull { it.id == panel.editing }
            ManualTemplateEditor(original, requireNotNull(panel.currency), panel.busy,
                ManualTemplateEditorActions(actions.save, original?.let { { actions.delete(it.id) } }, { actions.edit(null) }))
        }
        chosen != null -> key(panel.entryKey) {
            ManualExpenseSheet(
                state = ManualExpenseSheetState(ledger.categories, ledger.creatingManual,
                    initialCurrency = requireNotNull(CurrencyCode.fromStorageKeyOrNull(chosen.currencyCode)),
                    ledgerHomeCurrency = requireNotNull(panel.currency), errorMessage = ledger.manualCreateError?.asString(), editable = !ledger.readOnly),
                actions = ManualExpenseSheetActions(onCreate = entries.onManualCreate,
                    onDismiss = { actions.select(null); entries.onManualCreateSettled() }),
                initials = ManualExpenseSheetInitials(category = chosen.category, note = chosen.note,
                    amountMinor = chosen.amountMinor, categoryChoice = "manual"),
            )
        }
        else -> ManualTemplateList(panel.entries.orEmpty(), ledger.readOnly, actions)
    }
}

@Composable
private fun ManualTemplateList(entries: List<ManualEntryTemplate>, readOnly: Boolean, actions: ManualTemplatePanelActions) {
    Text(stringResource(R.string.widget_templates), style = MaterialTheme.typography.headlineSmall)
    Text(stringResource(R.string.widget_template_hint))
    if (readOnly) Text(stringResource(R.string.widget_template_read_only))
    if (entries.isEmpty()) Text(stringResource(R.string.widget_template_empty))
    entries.forEach { entry ->
        Column {
            Text(entry.name, style = MaterialTheme.typography.titleMedium)
            Text("${formatDisplayAmount(entry.amountMinor, CurrencyDisplay.forRecord(entry.currencyCode))} · ${entry.category}")
            if (entry.note.isNotBlank()) Text(entry.note, maxLines = 2)
            Row {
                Button(enabled = !readOnly, onClick = { actions.select(entry.id) }) { Text(stringResource(R.string.widget_template_use)) }
                TextButton(onClick = { actions.edit(entry.id) }) { Text(stringResource(R.string.widget_template_edit)) }
            }
        }
    }
    Button(onClick = { actions.edit("new") }) { Text(stringResource(R.string.widget_template_add)) }
}
