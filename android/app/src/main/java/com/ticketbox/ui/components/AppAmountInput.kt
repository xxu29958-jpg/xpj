package com.ticketbox.ui.components

import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.FocusState
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.domain.model.CurrencyCode

@Immutable
data class AppAmountInputState(
    val label: String,
    val currency: CurrencyCode,
    val value: String,
    val placeholder: String,
    val enabled: Boolean = true,
    val isError: Boolean = false,
)

data class AppAmountInputActions(
    val onValueChange: (String) -> Unit,
    val onFocusChanged: (FocusState) -> Unit = {},
)

@Composable
fun AppAmountInput(
    state: AppAmountInputState,
    actions: AppAmountInputActions,
    modifier: Modifier = Modifier,
    focusRequester: FocusRequester? = null,
    supportingText: (@Composable () -> Unit)? = null,
) {
    AppTextInput(
        state = AppTextInputState(
            label = state.label,
            value = state.value,
            placeholder = state.placeholder,
            trailingLabel = "${state.currency.symbol} ${state.currency.storageKey}",
            enabled = state.enabled,
            isError = state.isError,
            emphasis = AppTextInputEmphasis.Amount,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        ),
        actions = AppTextInputActions(
            onValueChange = actions.onValueChange,
            onFocusChanged = actions.onFocusChanged,
        ),
        modifier = modifier,
        focusRequester = focusRequester,
        supportingText = supportingText,
    )
}
