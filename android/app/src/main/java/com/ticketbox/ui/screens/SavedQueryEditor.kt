package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.remote.dto.SavedViewDefinitionRequestDto
import com.ticketbox.data.repository.SavedQueryCommand
import com.ticketbox.data.repository.SavedQueryDraft
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SavedQueryDraftState

data class SavedQueryEditorActions(
    val change: (SavedViewDefinitionRequestDto) -> Unit,
    val submit: () -> Unit,
    val review: () -> Unit,
    val acknowledge: () -> Unit,
    val retrySave: () -> Unit,
    val back: () -> Unit,
)

data class SavedQueryEditorContext(val ledgerName: String, val tags: List<ManagedTag>, val tagError: UiText?)

@Composable
fun SavedQueryEditor(draft: SavedQueryDraft, state: SavedQueryDraftState, context: SavedQueryEditorContext, actions: SavedQueryEditorActions) {
    val deleting = draft.command == SavedQueryCommand.Delete
    val enabled = state.canEdit(draft)
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(AppPageRole.Ledger,
            stringResource(if (deleting) R.string.saved_query_delete else R.string.saved_query_editor_title),
            stringResource(if (deleting) R.string.saved_query_delete_intro else R.string.saved_query_intro),
            stringResource(R.string.saved_query_back), actions.back,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)),
        bottomBar = {
            AppFloatingActionBar {
                AppPrimaryButton(stringResource(when {
                    draft.phase == "accepted" -> R.string.saved_query_done
                    draft.phase == "unconfirmed" -> R.string.saved_query_replay
                    deleting -> R.string.saved_query_delete
                    else -> R.string.saved_query_save
                }), modifier = Modifier.fillMaxWidth(),
                    enabled = if (draft.phase == "accepted") !state.busy && draft.binding == state.binding else state.canSubmit(draft),
                    onClick = if (draft.phase == "accepted") actions.acknowledge else actions.submit)
            }
        },
    ) {
        SavedQueryTaskStatus(draft, state, actions)
        if (deleting) {
            Text(draft.definition.name, style = MaterialTheme.typography.titleLarge)
            Text(savedQueryConditions(draft.definition, draft.baseline?.tagName))
        } else {
            SavedQueryCoreFields(draft, enabled, context, actions.change)
            SavedQueryAdditionalFields(draft.definition, enabled, actions.change)
        }
        Text(stringResource(R.string.saved_query_binding, context.ledgerName, draft.definition.homeCurrencyCode),
            style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun SavedQueryTaskStatus(draft: SavedQueryDraft, state: SavedQueryDraftState, actions: SavedQueryEditorActions) {
    if (!state.canModify) Text(stringResource(R.string.saved_query_readonly))
    state.error?.let {
        Text(it.asString(), color = MaterialTheme.colorScheme.error)
        AppSecondaryButton(stringResource(R.string.saved_query_retry), enabled = !state.busy, onClick = actions.retrySave)
    }
    draft.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    if (draft.phase == "unconfirmed") Text(stringResource(R.string.saved_query_unknown))
    if (draft.phase == "accepted") {
        Text(stringResource(R.string.saved_query_accepted))
        Text(draft.receipt?.name ?: draft.deletionReceipt?.name ?: draft.definition.name)
    }
    if (draft.binding != state.binding || draft.phase == "rejected") {
        AppSecondaryButton(stringResource(if (draft.binding != state.binding) R.string.saved_query_rebind else R.string.saved_query_review),
            enabled = state.canModify && !state.busy, onClick = actions.review)
    }
}

@Composable
private fun SavedQueryCoreFields(draft: SavedQueryDraft, enabled: Boolean, context: SavedQueryEditorContext,
    change: (SavedViewDefinitionRequestDto) -> Unit) {
    val fields = draft.definition
    AppTextInput(AppTextInputState(stringResource(R.string.saved_query_name), fields.name, enabled = enabled),
        AppTextInputActions(onValueChange = { change(fields.copy(name = it)) }))
    if (fields.filter.isEmpty()) {
        SavedQueryChoice(stringResource(R.string.saved_query_month), fields.monthMode,
            listOf("current" to stringResource(R.string.saved_query_current), "fixed" to stringResource(R.string.saved_query_fixed)), enabled) {
            change(fields.copy(monthMode = it))
        }
        if (fields.monthMode == "fixed") AppTextInput(AppTextInputState(stringResource(R.string.saved_query_fixed), fields.month.orEmpty(),
            placeholder = stringResource(R.string.saved_query_fixed_hint), enabled = enabled),
            AppTextInputActions(onValueChange = { change(fields.copy(month = it)) }))
    }
    AppTextInput(AppTextInputState(stringResource(R.string.saved_query_keyword), fields.queryText, enabled = enabled),
        AppTextInputActions(onValueChange = { change(fields.copy(queryText = it)) }))
    AppTextInput(AppTextInputState(stringResource(R.string.saved_query_category), fields.category,
        placeholder = stringResource(R.string.saved_query_category_hint), enabled = enabled),
        AppTextInputActions(onValueChange = { change(fields.copy(category = it)) }))
    context.tagError?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
    val tagOptions = listOf("" to stringResource(R.string.saved_query_no_tag)) + context.tags.map { it.publicId to it.name }
    val originalTag = fields.tagPublicId
    if (originalTag != null && context.tagError == null && tagOptions.none { it.first == originalTag }) {
        Text(draft.baseline?.tagName.orEmpty())
        Text(stringResource(R.string.saved_query_missing_tag), color = MaterialTheme.colorScheme.error)
    }
    SavedQueryChoice(stringResource(R.string.saved_query_tag), originalTag.orEmpty(), tagOptions, enabled && context.tagError == null) {
        change(fields.copy(tagPublicId = it.ifEmpty { null }))
    }
}

@Composable
private fun SavedQueryAdditionalFields(fields: SavedViewDefinitionRequestDto, enabled: Boolean,
    change: (SavedViewDefinitionRequestDto) -> Unit) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    AppSecondaryButton(stringResource(R.string.saved_query_more), onClick = { expanded = !expanded })
    if (expanded) {
        SavedQueryChoice(stringResource(R.string.saved_query_scope), fields.filter, listOf(
            "" to stringResource(R.string.saved_query_all),
            "missing_category" to stringResource(R.string.saved_query_missing_category),
            "missing_accounting_date" to stringResource(R.string.saved_query_missing_date)), enabled) { change(fields.copy(filter = it)) }
        SavedQueryChoice(stringResource(R.string.saved_query_currency), fields.homeCurrencyCode,
            CurrencyCode.entries.map { it.storageKey to it.displayName }, enabled) { change(fields.copy(homeCurrencyCode = it)) }
    }
}

@Composable
private fun SavedQueryChoice(label: String, selected: String, entries: List<Pair<String, String>>, enabled: Boolean, select: (String) -> Unit) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(label, style = MaterialTheme.typography.labelLarge)
        Box {
            AppSecondaryButton(entries.firstOrNull { it.first == selected }?.second ?: stringResource(R.string.saved_query_unavailable),
                modifier = Modifier.fillMaxWidth(), enabled = enabled, onClick = { expanded = true })
            DropdownMenu(expanded = expanded && enabled, onDismissRequest = { expanded = false }) {
                entries.forEach { (key, title) -> DropdownMenuItem(text = { Text(title) }, onClick = { select(key); expanded = false }) }
            }
        }
    }
}
