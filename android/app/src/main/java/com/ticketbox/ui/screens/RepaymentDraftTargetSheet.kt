package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.RepaymentDraftInboxUiState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun RepaymentDraftTargetSheet(state: RepaymentDraftInboxUiState, publicId: String?,
    onPick: (String, Debt) -> Unit, onClose: () -> Unit) {
    if (publicId == null || state.isLoading) return
    DebtPickerSheet(
        model = DebtPickerModel(state.targetDebts, state.suggestedDebtByDraftId[publicId]?.publicId),
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        onPick = { onPick(publicId, it) }, onClose = onClose,
    )
}

/** The picker's data: the repayable Debt list + which one (if any) the server suggested. */
private class DebtPickerModel(
    val debts: List<Debt>,
    val suggestedPublicId: String?,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DebtPickerSheet(
    model: DebtPickerModel,
    sheetState: androidx.compose.material3.SheetState,
    onPick: (Debt) -> Unit,
    onClose: () -> Unit,
) {
    // Pin the suggested Debt to the top (stable sort keeps the rest in order); it also gets a badge.
    val ordered = remember(model.debts, model.suggestedPublicId) {
        model.debts.sortedByDescending { it.publicId == model.suggestedPublicId }
    }
    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        AppSheetScaffold(title = stringResource(R.string.repayment_draft_picker_title)) {
            if (ordered.isEmpty()) {
                Text(
                    stringResource(R.string.repayment_draft_picker_empty),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                ordered.forEachIndexed { index, debt ->
                    DebtPickerRow(
                        debt = debt,
                        isSuggested = debt.publicId == model.suggestedPublicId,
                        showDivider = index != ordered.lastIndex,
                        onPick = { onPick(debt) },
                    )
                }
            }
        }
    }
}

@Composable
private fun DebtPickerRow(
    debt: Debt,
    isSuggested: Boolean,
    showDivider: Boolean,
    onPick: () -> Unit,
) {
    AppListRow(
        onClick = onPick,
        showDivider = showDivider,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(debtPickerLabel(debt), style = MaterialTheme.typography.bodyLarge)
                if (isSuggested) {
                    Spacer(Modifier.width(AppSpacing.smallGap))
                    Text(
                        stringResource(R.string.repayment_draft_picker_suggested_badge),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
        Spacer(Modifier.width(AppSpacing.smallGap))
        AppEndAlignedAmountText(
            stringResource(
                R.string.repayment_draft_picker_remaining,
                // 同上：record 级 homeCurrencyCode 口径（PR#255 R5 P1）。
                formatDisplayAmount(debt.remainingAmountCents, CurrencyDisplay.forRecord(debt.homeCurrencyCode)),
            ),
            modifier = Modifier.weight(0.42f),
            role = AppAmountRole.Compact,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** Display label for a target Debt: its counterparty label, or the type fallback when unlabeled. */
@Composable
internal fun debtPickerLabel(debt: Debt): String =
    debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
