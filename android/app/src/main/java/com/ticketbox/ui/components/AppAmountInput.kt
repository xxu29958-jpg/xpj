package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.FocusState
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum

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
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = state.label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelLarge,
            )
            Text(
                text = "${state.currency.symbol} ${state.currency.storageKey}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        OutlinedTextField(
            value = state.value,
            onValueChange = actions.onValueChange,
            modifier = Modifier
                .fillMaxWidth()
                .then(if (focusRequester != null) Modifier.focusRequester(focusRequester) else Modifier)
                .onFocusChanged(actions.onFocusChanged),
            placeholder = { Text(state.placeholder) },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            singleLine = true,
            enabled = state.enabled,
            isError = state.isError,
            textStyle = MaterialTheme.typography.titleLarge.tabularNum(),
            shape = RoundedCornerShape(AppRadius.extraSmall),
        )
        supportingText?.invoke()
    }
}
