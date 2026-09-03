package com.ticketbox.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.FocusState
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing

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
    /**
     * 非空时金额框内的币种尾随（¥ CNY ⌄）可点，用于展开币种选择；null 保持
     * 原有纯展示尾随。只读页面传 null，币种永远没有写 affordance。
     */
    val onCurrencyClick: (() -> Unit)? = null,
)

@Composable
fun AppAmountInput(
    state: AppAmountInputState,
    actions: AppAmountInputActions,
    modifier: Modifier = Modifier,
    focusRequester: FocusRequester? = null,
    supportingText: (@Composable () -> Unit)? = null,
) {
    val currencyTrailing = state.currency.trailingLabel()
    AppTextInput(
        state = AppTextInputState(
            label = state.label,
            value = state.value,
            placeholder = state.placeholder,
            // 可点币种并入金额框内尾随；不可点时维持 label 行右侧的纯展示尾随。
            trailingLabel = currencyTrailing.takeIf { actions.onCurrencyClick == null },
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
        decorations = AppTextInputDecorations(
            trailingContent = actions.onCurrencyClick?.let { onCurrencyClick ->
                {
                    AppAmountInputCurrencyTrailing(
                        text = currencyTrailing,
                        enabled = state.enabled,
                        onClick = onCurrencyClick,
                    )
                }
            },
            supportingText = supportingText,
        ),
    )
}

private fun CurrencyCode.trailingLabel(): String = "$symbol $storageKey"

@Composable
private fun AppAmountInputCurrencyTrailing(
    text: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val contentColor = if (enabled) {
        MaterialTheme.colorScheme.onSurfaceVariant
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.strong)
    }
    Row(
        modifier = Modifier
            // 纯文字尾随只有一行字高，靠 minimumInteractiveComponentSize 把触控区补到 48dp 底线。
            .minimumInteractiveComponentSize()
            .clickable(
                enabled = enabled,
                onClickLabel = stringResource(R.string.components_amount_input_switch_currency),
                role = Role.Button,
                onClick = onClick,
            )
            .padding(start = AppSpacing.miniGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = text,
            color = contentColor,
            style = MaterialTheme.typography.labelMedium,
            maxLines = 1,
        )
        Icon(
            imageVector = Icons.Filled.ExpandMore,
            contentDescription = null,
            tint = contentColor,
            modifier = Modifier.size(AppSpacing.compactGap),
        )
    }
}
