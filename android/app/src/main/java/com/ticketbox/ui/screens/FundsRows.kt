package com.ticketbox.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.FinancialAccount
import com.ticketbox.domain.model.FundMovement
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

/** The words and amount of one account or movement row. */
@Immutable
internal data class FundsRowModel(val icon: Int, val title: String, val subtitle: String, val amount: String?)

/** One account or movement: icon tile, title and context, and an end-aligned amount that wraps at large font sizes. */
@Composable
internal fun FundsIconRow(model: FundsRowModel, onClick: (() -> Unit)?,
    iconBackground: Color = LocalThemeVisuals.current.brandPrimaryBg, extra: @Composable ColumnScope.() -> Unit = {}) {
    val (icon, title, subtitle, amount) = model
    Column(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)) {
        AppAdaptiveContentActionRow(
            modifier = Modifier.padding(vertical = AppSpacing.compactGap),
            style = AppAdaptiveContentActionStyle(compactAction = true, amountTrailing = true, verticalAlignment = Alignment.Top),
            content = {
                Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap), verticalAlignment = Alignment.Top) {
                    SettingsEntryIcon(ImageVector.vectorResource(icon), background = iconBackground)
                    Column {
                        Text(title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                        Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        extra()
                    }
                }
            },
            action = { modifier -> amount?.let { Text(it, modifier = modifier, style = MaterialTheme.typography.bodyMedium.tabularNum(),
                fontWeight = FontWeight.SemiBold) } },
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

internal fun fundKindIcon(kind: String): Int = when (kind) {
    "cash" -> R.drawable.ic_lucide_banknote
    "wallet" -> R.drawable.ic_lucide_wallet
    "credit" -> R.drawable.ic_lucide_credit_card
    else -> R.drawable.ic_lucide_landmark
}

@Composable
internal fun FinancialAccount.balanceText(): String = when {
    balanceMinor == null -> stringResource(R.string.funds_unknown_balance)
    kind == "credit" && balanceMinor <= 0 -> stringResource(R.string.funds_debt_balance, money(-balanceMinor, currencyCode))
    kind == "credit" -> stringResource(R.string.funds_overpayment_balance, money(balanceMinor, currencyCode))
    else -> money(balanceMinor, currencyCode)
}

private val movementLabels = mapOf(
    "opening" to R.string.funds_movement_opening, "income" to R.string.funds_movement_income,
    "repayment" to R.string.funds_movement_repayment, "reconciliation" to R.string.funds_movement_reconciliation,
    "expense" to R.string.funds_movement_expense, "credit_draw" to R.string.funds_movement_credit_draw,
    "refund" to R.string.funds_movement_refund, "reversal" to R.string.funds_movement_reversal,
    "correction" to R.string.funds_movement_correction, "fee" to R.string.funds_movement_fee,
)

/** What kind of change a movement was, in the same words as the web account page. */
@Composable
internal fun FundMovement.label(accountKind: String): String = stringResource(when (kind) {
    "transfer" -> if (amountMinor < 0) R.string.funds_movement_transfer_out else R.string.funds_movement_transfer_in
    "loan" -> if (accountKind == "credit") R.string.funds_movement_loan_principal else R.string.funds_movement_loan
    else -> movementLabels[kind] ?: R.string.funds_movement_other
})

/** Inflows carry an explicit plus; outflows keep the shared negative money format. */
internal fun signedMoney(value: Long, currency: String): String = (if (value > 0) "+" else "") + money(value, currency)

/** What a movement row can open or correct; a null action is not offered to this person. */
internal data class FundsMovementActions(
    val openExpense: (Long) -> Unit,
    val voidActivity: ((FundMovement) -> Unit)?,
    val voidPayment: ((String) -> Unit)?,
    val reconcile: (() -> Unit)?,
)

/** A recorded change to the account: what it was, when and why, the signed amount, and the corrections it allows. */
@Composable
internal fun FundsMovementRow(row: FundMovement, account: FinancialAccount, actions: FundsMovementActions) {
    FundsIconRow(FundsRowModel(
        icon = R.drawable.ic_lucide_receipt_text,
        title = row.label(account.kind),
        subtitle = if (row.note.isBlank()) row.occurredOn else stringResource(R.string.funds_movement_meta, row.occurredOn, row.note),
        amount = signedMoney(row.amountMinor, account.currencyCode),
    ), onClick = null) {
        if (row.voided) Text(stringResource(R.string.funds_activity_voided), style = MaterialTheme.typography.bodySmall)
        val voidActivity = actions.voidActivity?.takeIf { row.correctionParts.isNotEmpty() }
        val voidPayment = actions.voidPayment?.takeIf { row.canVoidRepayment }
        val reconcile = actions.reconcile?.takeIf { row.kind == "opening" || row.kind == "reconciliation" }
        row.expenseId?.let { id -> FundsRowLink(stringResource(R.string.funds_view_expense)) { actions.openExpense(id) } }
        voidActivity?.let { FundsRowLink(stringResource(R.string.funds_void_activity)) { it(row) } }
        row.repaymentPublicId?.let { id -> voidPayment?.let { FundsRowLink(stringResource(R.string.funds_void_payment)) { it(id) } } }
        reconcile?.let { FundsRowLink(stringResource(R.string.funds_reconcile_again), it) }
    }
}

@Composable
internal fun FundsRowLink(label: String, onClick: () -> Unit) {
    TextButton(onClick = onClick, contentPadding = PaddingValues(horizontal = AppSpacing.none)) { Text(label) }
}
