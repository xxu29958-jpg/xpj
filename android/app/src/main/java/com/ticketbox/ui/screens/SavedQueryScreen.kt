package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.graphics.vector.ImageVector
import com.ticketbox.R
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.remote.dto.SavedViewDefinitionRequestDto
import com.ticketbox.data.remote.dto.SavedViewDto
import com.ticketbox.data.remote.dto.SavedViewResultRowDto
import com.ticketbox.data.repository.SavedQueryDraft
import com.ticketbox.data.repository.queryDefinition
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SavedQueryDraftState
import com.ticketbox.viewmodel.SavedQueryUiState

data class SavedQueryActions(
    val back: () -> Unit,
    val create: () -> Unit,
    val open: (String, Int) -> Unit,
    val edit: (SavedViewDto, Boolean) -> Unit,
    val resume: (SavedQueryDraft) -> Unit,
    val refresh: () -> Unit,
    val openExpense: (Long) -> Unit,
    val repairRate: (MissingExchangeRateDto) -> Unit,
)

@Composable
fun SavedQueryScreen(state: SavedQueryUiState, drafts: SavedQueryDraftState, actions: SavedQueryActions) {
    val selected = state.catalog?.firstOrNull { it.publicId == state.selectedId }
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(AppPageRole.Ledger, selected?.name ?: stringResource(R.string.saved_query_title),
            stringResource(R.string.saved_query_intro), stringResource(R.string.saved_query_back), actions.back,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)),
    ) {
        if (!drafts.canModify) Text(stringResource(R.string.saved_query_readonly))
        if (state.loading) Text(stringResource(R.string.saved_query_loading))
        state.error?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
        drafts.error?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
        if (state.error != null || drafts.error != null) AppSecondaryButton(stringResource(R.string.saved_query_retry), onClick = actions.refresh)
        if (state.selectedId == null) SavedQueryDirectory(state, drafts, actions) else SavedQueryResults(state, drafts.canModify, selected, actions)
    }
}

@Composable
private fun SavedQueryDirectory(state: SavedQueryUiState, drafts: SavedQueryDraftState, actions: SavedQueryActions) {
    AppPrimaryButton(stringResource(R.string.saved_query_create), modifier = Modifier.fillMaxWidth(),
        enabled = drafts.ready && drafts.canModify && !drafts.busy, onClick = actions.create)
    if (drafts.drafts.isNotEmpty()) {
        AppSectionHeader(stringResource(R.string.saved_query_retained))
        drafts.drafts.forEach { draft ->
            AppListRow(onClick = { actions.resume(draft) }) {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
                    Text(draft.definition.name.ifBlank { stringResource(R.string.saved_query_editor_title) }, style = MaterialTheme.typography.titleMedium)
                    Text(stringResource(when (draft.phase) {
                        "accepted" -> R.string.saved_query_accepted
                        "unconfirmed" -> R.string.saved_query_unknown
                        else -> R.string.saved_query_retained
                    }))
                }
            }
        }
    }
    state.catalog?.let { catalog ->
        if (catalog.isEmpty()) Text(stringResource(R.string.saved_query_empty))
        catalog.forEach { query ->
            AppListRow(onClick = { actions.open(query.publicId, 1) }) {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
                    Text(query.name, style = MaterialTheme.typography.titleLarge)
                    Text(savedQueryConditions(query.queryDefinition(), query.tagName))
                    if (query.repairReason != null) Text(stringResource(R.string.saved_query_missing_tag), color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}

@Composable
private fun SavedQueryResults(state: SavedQueryUiState, canModify: Boolean, selected: SavedViewDto?, actions: SavedQueryActions) {
    if (selected != null) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppSecondaryButton(stringResource(R.string.saved_query_edit), enabled = canModify, onClick = { actions.edit(selected, false) })
            AppSecondaryButton(stringResource(R.string.saved_query_delete), enabled = canModify, onClick = { actions.edit(selected, true) })
        }
    }
    val result = state.results ?: return
    Text(listOfNotNull(result.conditions["month"], result.conditions["q"], result.conditions["category"], result.conditions["tag"],
        result.conditions["home_currency_code"], queryScopeLabel(result.conditions["filter"].orEmpty())).filter { it.isNotBlank() }.joinToString(" · "))
    AppSectionHeader(stringResource(R.string.saved_query_result_count, result.total, result.page))
    if (result.items.isEmpty()) Text(stringResource(R.string.saved_query_no_results))
    val currency = requireNotNull(result.conditions["home_currency_code"])
    result.items.forEach { row -> SavedQueryResult(row, currency, canModify, actions) }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (result.page > 1) AppSecondaryButton(stringResource(R.string.saved_query_previous), onClick = { actions.open(requireNotNull(state.selectedId), result.page - 1) })
        if (result.page.toLong() * result.pageSize < result.total) AppSecondaryButton(stringResource(R.string.saved_query_next), onClick = { actions.open(requireNotNull(state.selectedId), result.page + 1) })
    }
}

@Composable
private fun SavedQueryResult(row: SavedViewResultRowDto, currency: String, canModify: Boolean, actions: SavedQueryActions) {
    val entry = row.entry
    val originalMinor = entry.offset?.originalAmountMinor ?: entry.root.originalAmountMinor
    val originalCurrency = entry.offset?.originalCurrencyCode ?: entry.root.originalCurrencyCode
    AppListRow(onClick = { actions.openExpense(entry.root.id) }) {
        SettingsEntryIcon(ImageVector.vectorResource(R.drawable.ic_lucide_receipt_text))
        Spacer(Modifier.width(AppSpacing.contentGap))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppAdaptiveEditAmountRow(amount = row.projectedAmountCents?.let { formatDisplayAmount(it, CurrencyDisplay.forRecord(currency)) }.orEmpty(),
                style = AppAdaptiveAmountRowStyle(trailingWeight = AppAdaptiveAmountRowDefaults.listTrailingWeight)) {
                Text(entry.root.merchant ?: entry.root.category, style = MaterialTheme.typography.titleMedium)
            }
            Text(listOfNotNull(entry.streamDate, entry.offset?.category ?: entry.root.category).joinToString(" · "),
                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            if (entry.offset != null) Text(stringResource(R.string.saved_query_offset))
            if (originalMinor != null && originalCurrency != null) Text(stringResource(R.string.saved_query_original,
                "${formatDisplayAmount(originalMinor, CurrencyDisplay.forRecord(originalCurrency))} $originalCurrency"))
            row.projectionGap?.let { gap ->
                Text(stringResource(R.string.saved_query_projection_missing))
                if (canModify && gap.canEnterManualRate()) AppSecondaryButton(stringResource(R.string.saved_query_rate_repair),
                    onClick = { actions.repairRate(gap) })
            }
        }
    }
}

@Composable
internal fun savedQueryConditions(query: SavedViewDefinitionRequestDto, tagName: String?): String = listOfNotNull(
    if (query.filter.isEmpty()) {
        if (query.monthMode == "current") stringResource(R.string.saved_query_current) else query.month
    } else queryScopeLabel(query.filter), query.queryText, query.category, tagName, query.homeCurrencyCode,
).filter { it.isNotBlank() }.joinToString(" · ")

@Composable
private fun queryScopeLabel(filter: String): String = when (filter) {
    "missing_category" -> stringResource(R.string.saved_query_missing_category)
    "missing_accounting_date" -> stringResource(R.string.saved_query_missing_date)
    else -> ""
}
