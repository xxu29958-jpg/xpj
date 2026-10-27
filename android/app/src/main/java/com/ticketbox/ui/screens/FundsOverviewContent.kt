package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.FinancialAccount
import com.ticketbox.domain.model.FundsOverview
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.FundsUiState

/** What the accounts overview can do; the screen wires these to the view model. */
internal data class FundsOverviewActions(
    val open: (String) -> Unit,
    val create: () -> Unit,
    val envelopes: () -> Unit,
    val resume: () -> Unit,
)

/**
 * The accounts overview, matching the web page: one net-worth summary, everyday and credit
 * accounts in their own groups, archived accounts folded, and the envelope plan as an entry.
 * Adding an account lives in the screen's bottom action bar.
 */
internal fun LazyListScope.fundsOverview(state: FundsUiState, actions: FundsOverviewActions) {
    if (state.task.input != null) item { AppSecondaryButton(stringResource(R.string.funds_resume_task), onClick = actions.resume) }
    val open = state.accounts.filterNot { it.archived }
    if (state.accounts.isEmpty()) {
        if (!state.loading) item { FundsEmptyState(canCreate = state.access?.canModify == true, onCreate = actions.create) }
        return
    }
    state.overview?.let { summary -> item { FundsNetWorthCard(summary) } }
    listOf(R.string.funds_group_everyday to open.filterNot { it.kind == "credit" }, R.string.funds_group_credit to open.filter { it.kind == "credit" })
        .filter { (_, rows) -> rows.isNotEmpty() }
        .forEach { (title, rows) ->
            item(key = "group:$title") { FundsGroupTitle(stringResource(title)) }
            items(rows, key = { it.publicId }) { account -> FundsAccountRow(account) { actions.open(account.publicId) } }
        }
    val archived = state.accounts.filter { it.archived }
    if (archived.isNotEmpty()) item(key = "archived") { FundsArchivedAccounts(archived, actions.open) }
    item(key = "envelopes") { FundsEnvelopeEntry(actions.envelopes) }
}

@Composable
private fun FundsNetWorthCard(summary: FundsOverview) {
    FundsHeroCard(
        label = stringResource(R.string.funds_summary_label, summary.valuationDate),
        amount = money(summary.netWorthMinor, summary.homeCurrencyCode),
    ) {
        Text(stringResource(R.string.funds_assets_liabilities, money(summary.assetsMinor, summary.homeCurrencyCode),
            money(summary.liabilitiesMinor, summary.homeCurrencyCode)), style = MaterialTheme.typography.bodyMedium.tabularNum())
        val excluded = listOfNotNull(
            summary.unknownAccounts.takeIf { it > 0 }?.let { stringResource(R.string.funds_summary_unknown, it) },
            summary.missingRateAccounts.takeIf { it > 0 }?.let { stringResource(R.string.funds_summary_missing_rate, it) },
        )
        if (excluded.isNotEmpty()) Text(stringResource(R.string.funds_summary_excluded, excluded.joinToString("，")),
            style = MaterialTheme.typography.bodySmall)
        Text(stringResource(R.string.funds_summary_note), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** The one tinted summary surface used for net worth and for an account's balance. */
@Composable
internal fun FundsHeroCard(label: String, amount: String, details: @Composable () -> Unit) {
    Surface(shape = RoundedCornerShape(AppRadius.hero), color = LocalThemeVisuals.current.brandPrimaryBg, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            AppAmountText(amount, modifier = Modifier.fillMaxWidth(), role = AppAmountRole.Hero)
            details()
        }
    }
}

@Composable
private fun FundsGroupTitle(title: String) {
    Text(title, modifier = Modifier.padding(top = AppSpacing.sectionGap), style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold)
}

@Composable
internal fun FundsAccountRow(account: FinancialAccount, onClick: () -> Unit) {
    val visibility = stringResource(if (account.visibility == "private") R.string.funds_private_visibility else R.string.funds_ledger_visibility)
    FundsIconRow(FundsRowModel(
        icon = fundKindIcon(account.kind),
        title = account.name + (account.tail?.let { " · $it" } ?: ""),
        subtitle = stringResource(R.string.funds_account_meta, fundKinds()[account.kind].orEmpty(), account.currencyCode, visibility) +
            if (account.archived) stringResource(R.string.funds_archived_suffix) else "",
        amount = account.balanceText(),
    ), onClick = onClick)
}

@Composable
private fun FundsArchivedAccounts(archived: List<FinancialAccount>, open: (String) -> Unit) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    Column {
        TextButton(onClick = { expanded = !expanded }) {
            Text(if (expanded) stringResource(R.string.funds_archived_hide) else stringResource(R.string.funds_archived_show, archived.size))
        }
        if (expanded) archived.forEach { account -> FundsAccountRow(account) { open(account.publicId) } }
    }
}

@Composable
private fun FundsEnvelopeEntry(onClick: () -> Unit) {
    Column(Modifier.padding(top = AppSpacing.sectionGap)) {
        FundsIconRow(FundsRowModel(R.drawable.ic_lucide_layers, stringResource(R.string.envelopes_title),
            stringResource(R.string.funds_envelopes_entry_body), amount = null), onClick = onClick,
            iconBackground = LocalThemeVisuals.current.surfaceLilac)
    }
}

@Composable
private fun FundsEmptyState(canCreate: Boolean, onCreate: () -> Unit) {
    AppEmptyStateCard {
        Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(stringResource(R.string.funds_empty_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.funds_empty_accounts), style = MaterialTheme.typography.bodyMedium)
            if (canCreate) AppPrimaryButton(stringResource(R.string.funds_add_account), modifier = Modifier.fillMaxWidth(), onClick = onCreate)
        }
    }
}
