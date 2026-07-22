package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.isUsablePendingMerchantText
import com.ticketbox.domain.model.pendingMerchantPresentation
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState

@Composable
internal fun QuickMerchantSheetContent(
    expense: Expense,
    chrome: ReviewSheetChrome,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val saving = chrome.saving
    var value by remember(expense.id) {
        mutableStateOf(pendingMerchantPresentation(expense).primaryText.orEmpty())
    }
    val cleaned = value.trim()
    val noiseLike = cleaned.isNotEmpty() && !isUsablePendingMerchantText(cleaned)
    // 保存守卫与 QuickCategory 同型（PR #230 round 9）：噪音文本（时间/日期串、
    // 单字符等）不允许"修好"一张票——保存键只在输入满足可用性判定才启用。
    val saveEnabled = quickMerchantSaveEnabled(value)
    // P1-2: single-field sheet — auto-focus so the keyboard pops on open.
    val focusRequester = remember { FocusRequester() }
    LaunchedEffect(Unit) { focusRequester.requestFocus() }

    ReviewSheetScaffold(
        title = stringResource(R.string.pending_quick_merchant_title),
        subtitle = stringResource(R.string.pending_quick_merchant_hint),
        chrome = chrome,
    ) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.pending_quick_merchant_label),
                value = value,
                placeholder = stringResource(R.string.pending_quick_merchant_placeholder),
                enabled = !saving,
                isError = (value.isNotEmpty() && cleaned.isEmpty()) || noiseLike,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None),
            ),
            actions = AppTextInputActions(onValueChange = { value = it.take(40) }),
            modifier = Modifier.fillMaxWidth(),
            focusRequester = focusRequester,
            decorations = AppTextInputDecorations(
                supportingText = quickMerchantSupportingText(value, cleaned, noiseLike),
            ),
        )

        ReviewSheetActionFeedback(
            chrome = chrome,
            primary = AppSheetAction(
                text = if (saving) stringResource(R.string.common_saving) else stringResource(R.string.pending_quick_merchant_save_button),
                enabled = !saving && saveEnabled,
                onClick = { onSave(cleaned) },
            ),
            secondary = AppSheetAction(
                text = stringResource(R.string.common_cancel),
                enabled = !saving,
                onClick = onDismiss,
            ),
        )
    }
}

internal fun quickMerchantSaveEnabled(value: String): Boolean {
    val cleaned = value.trim()
    // 单侧（客户端）守卫：merchant 是自由文本、可用性只是审阅启发式而非有效性
    // 契约（与类目的封闭 token 表不同）——服务端对显式写入维持 main 的放行语义。
    return cleaned.isNotEmpty() && isUsablePendingMerchantText(cleaned)
}

@Composable
private fun quickMerchantSupportingText(
    value: String,
    cleaned: String,
    noiseLike: Boolean,
): (@Composable () -> Unit)? = when {
    value.isNotEmpty() && cleaned.isEmpty() -> {
        {
            Text(
                stringResource(R.string.pending_quick_merchant_blank_error),
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
    noiseLike -> {
        {
            Text(
                stringResource(R.string.pending_quick_merchant_noise_error),
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
    else -> null
}
