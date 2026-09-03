package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.FxContract
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.sanitizeMinorAmountInput
import com.ticketbox.ui.design.AppSpacing

@Immutable
internal data class ExpenseEditAmountClusterState(
    val currency: CurrencyCode,
    val amountText: String,
    val currencyExpanded: Boolean,
    val enabled: Boolean,
)

@Immutable
internal data class ExpenseEditAmountClusterActions(
    val onCurrencyChange: (CurrencyCode) -> Unit,
    val onAmountChange: (String) -> Unit,
    val onAmountFocusChanged: (Boolean) -> Unit,
    val onToggleCurrency: () -> Unit,
)

/**
 * 金额簇：金额输入为主，币种收进框内可点尾随（¥ CNY ⌄），点开展开完整币种
 * chips；独立币种 summary 行不再占首屏。外币保留 FX 提示。输入沿用既有
 * [sanitizeMinorAmountInput] 口径；切币种后的金额重算由调用方声明。
 */
@Composable
internal fun ExpenseEditAmountCluster(
    state: ExpenseEditAmountClusterState,
    actions: ExpenseEditAmountClusterActions,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        AppAmountInput(
            state = AppAmountInputState(
                label = stringResource(R.string.expense_edit_amount_field_label),
                currency = state.currency,
                value = state.amountText,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = state.enabled,
            ),
            actions = AppAmountInputActions(
                onValueChange = { raw ->
                    actions.onAmountChange(sanitizeMinorAmountInput(raw, state.currency))
                },
                onFocusChanged = { actions.onAmountFocusChanged(it.isFocused) },
                onCurrencyClick = actions.onToggleCurrency.takeIf { state.enabled },
            ),
            supportingText = if (state.currency != FxContract.HomeCurrency) {
                {
                    Text(
                        text = stringResource(R.string.expense_edit_fx_hint),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            } else {
                null
            },
        )
        if (state.currencyExpanded) {
            ExpenseCurrencyChoices(
                currency = state.currency,
                enabled = state.enabled,
                onCurrencySelect = actions.onCurrencyChange,
            )
        }
    }
}
