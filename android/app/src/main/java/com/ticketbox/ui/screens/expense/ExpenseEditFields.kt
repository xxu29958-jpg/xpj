package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppFilterChipOptions
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun OcrProgressCard() {
    AppLoadingState(
        title = stringResource(R.string.expense_edit_ocr_progress_title),
        body = stringResource(R.string.expense_edit_ocr_progress_body),
    )
}

@Composable
internal fun ExpenseRepaymentDraftPanel(
    creating: Boolean,
    onCreate: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppSectionHeader(
            title = stringResource(R.string.expense_edit_repayment_draft_card_title),
            subtitle = stringResource(R.string.expense_edit_repayment_draft_card_subtitle),
        )
        AppOutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            options = AppOutlinedButtonOptions(enabled = !creating),
            onClick = onCreate,
        ) {
            Text(
                if (creating) {
                    stringResource(R.string.expense_edit_repayment_draft_processing_button)
                } else {
                    stringResource(R.string.expense_edit_repayment_draft_button)
                },
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        ExpenseEditRowDivider()
    }
}

@Composable
internal fun SelectableCategoryChip(
    selected: Boolean,
    label: String,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    AppFilterChip(
        selected = selected,
        onClick = onClick,
        label = label,
        options = AppFilterChipOptions(enabled = enabled),
    )
}

@Composable
private fun ExpenseEditRowDivider() {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
}
