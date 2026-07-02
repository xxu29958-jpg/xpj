package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatExpenseExchangeMeta
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

internal data class EditDraftPreviewState(
    val expense: Expense,
    val previewImage: ProtectedImage?,
    val imageLoading: Boolean,
    val ocrRunning: Boolean,
    val readOnly: Boolean,
    val showLargeImage: Boolean,
)

internal data class EditDraftPreviewActions(
    val onToggleLargeImage: () -> Unit,
    val onRetryOcr: () -> Unit,
)

internal data class ExpenseDateFieldState(
    val expenseTime: String,
    val enabled: Boolean = true,
)

internal data class ExpenseDateFieldActions(
    val onPickDate: () -> Unit,
    val onPickTime: () -> Unit,
    val onUseNow: () -> Unit,
    val onClear: () -> Unit,
)

@Composable
internal fun EditDraftPreviewCard(
    state: EditDraftPreviewState,
    actions: EditDraftPreviewActions,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (state.expense.imagePath != null) {
                AppAsyncImage(
                    image = state.previewImage,
                    placeholder = if (state.imageLoading) {
                        stringResource(R.string.expense_edit_preview_image_loading)
                    } else {
                        stringResource(R.string.expense_edit_preview_image_saved)
                    },
                    contentScale = ContentScale.Crop,
                    compact = true,
                    compactSize = DpSize(width = 104.dp, height = 136.dp),
                )
            }
            EditDraftPreviewDetails(
                modifier = Modifier.weight(1f),
                state = state,
                actions = actions,
            )
        }
        ExpenseEditRowDivider()
    }
}

@Composable
private fun EditDraftPreviewDetails(
    state: EditDraftPreviewState,
    actions: EditDraftPreviewActions,
    modifier: Modifier = Modifier,
) {
    val expense = state.expense
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.expense_edit_preview_draft_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
        )
        Text(
            text = expense.merchant?.takeIf { it.isNotBlank() }
                ?: stringResource(R.string.expense_edit_preview_merchant_empty),
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = formatExpensePrimaryAmount(expense, currencyDisplay),
            style = MaterialTheme.typography.headlineMedium.tabularNum(),
            color = MaterialTheme.colorScheme.onSurface,
            autoSize = TextAutoSize.StepBased(minFontSize = 18.sp, maxFontSize = 28.sp, stepSize = 1.sp),
            maxLines = 1,
            overflow = TextOverflow.Clip,
        )
        formatExpenseExchangeMeta(expense)?.let { meta ->
            Text(
                text = meta,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        EditDraftPreviewPills(expense)
        if (expense.imagePath != null) {
            EditDraftPreviewActionsRow(state = state, actions = actions)
        }
    }
}

@Composable
private fun EditDraftPreviewPills(expense: Expense) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        StatusPill(expense.category)
        expense.confidence?.let {
            StatusPill(
                stringResource(R.string.expense_edit_preview_confidence_pill, (it * 100).toInt()),
                active = false,
            )
        }
    }
}

@Composable
private fun EditDraftPreviewActionsRow(
    state: EditDraftPreviewState,
    actions: EditDraftPreviewActions,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        AppOutlinedButton(
            modifier = Modifier
                .weight(0.82f)
                .height(AppSpacing.controlMinHeight),
            enabled = !state.imageLoading,
            contentPadding = PaddingValues(horizontal = AppSpacing.smallGap, vertical = 0.dp),
            onClick = actions.onToggleLargeImage,
        ) {
            PreviewActionText(
                when {
                    state.imageLoading -> stringResource(R.string.expense_edit_preview_image_button_loading)
                    state.showLargeImage -> stringResource(R.string.expense_edit_preview_image_button_collapse)
                    else -> stringResource(R.string.expense_edit_preview_image_button_open)
                },
            )
        }
        if (!state.readOnly) {
            AppOutlinedButton(
                modifier = Modifier
                    .weight(1f)
                    .height(AppSpacing.controlMinHeight),
                enabled = !state.ocrRunning,
                contentPadding = PaddingValues(horizontal = AppSpacing.smallGap, vertical = 0.dp),
                onClick = actions.onRetryOcr,
            ) {
                PreviewActionText(
                    if (state.ocrRunning) {
                        stringResource(R.string.expense_edit_preview_recognize_running_button)
                    } else {
                        stringResource(R.string.expense_edit_preview_recognize_retry_button)
                    },
                )
            }
        }
    }
}

@Composable
private fun PreviewActionText(text: String) {
    Text(
        text = text,
        maxLines = 1,
        softWrap = false,
        overflow = TextOverflow.Ellipsis,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = AppTextHierarchy.body.weight,
    )
}

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
            enabled = !creating,
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
        enabled = enabled,
        leadingIcon = if (selected) {
            {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = null,
                    modifier = Modifier.size(FilterChipDefaults.IconSize),
                )
            }
        } else {
            null
        },
    )
}

@Composable
internal fun ExpenseDateField(
    state: ExpenseDateFieldState,
    actions: ExpenseDateFieldActions,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppSectionHeader(title = stringResource(R.string.expense_edit_date_section_title))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                modifier = Modifier.weight(1f),
                text = displayDateTime(state.expenseTime),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            AppOutlinedButton(enabled = state.enabled, onClick = actions.onPickDate) {
                Text(stringResource(R.string.expense_edit_date_pick_date_button))
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            TextButton(enabled = state.enabled, onClick = actions.onPickTime) {
                Text(stringResource(R.string.expense_edit_date_pick_time_button))
            }
            TextButton(enabled = state.enabled, onClick = actions.onUseNow) {
                Text(stringResource(R.string.expense_edit_date_use_now_button))
            }
            TextButton(
                enabled = state.enabled && state.expenseTime.isNotBlank(),
                onClick = actions.onClear,
            ) {
                Text(stringResource(R.string.expense_edit_date_clear_button))
            }
        }
        ExpenseEditRowDivider()
    }
}

@Composable
private fun ExpenseEditRowDivider() {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
}
