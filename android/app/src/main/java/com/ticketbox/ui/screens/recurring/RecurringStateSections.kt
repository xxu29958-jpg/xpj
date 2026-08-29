package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringPendingState
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalStateTokens

/**
 * 系统状态呈现层（不另造状态 Owner，全部从 RecurringUiState 派生）：
 * - 待同步 intent：WAITING/CONFLICT/FAILED 三态诚实标签 + UPDATE 基线解析，不计总额。
 * - recurring_item_conflict：可行动出口（编辑现有 / 恢复归档），不只红色错误。
 */

@Composable
internal fun RecurringPendingSection(
    intents: List<RecurringPendingIntent>,
    items: List<RecurringItem>,
    currencyDisplay: CurrencyDisplay,
) {
    AppSectionGroup(
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(
                text = stringResource(R.string.recurring_pending_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.recurring_pending_note),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        intents.forEachIndexed { index, intent ->
            if (index > 0) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
            }
            RecurringPendingRow(
                model = resolveRecurringPendingRow(intent, items),
                intentState = intent.state,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

@Composable
private fun RecurringPendingRow(
    model: RecurringPendingRowModel,
    intentState: RecurringPendingState,
    currencyDisplay: CurrencyDisplay,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            RecurringPendingRowTexts(
                model = model,
                intentState = intentState,
                currencyDisplay = currencyDisplay,
            )
        }
        model.amountCents?.let {
            Text(
                text = formatDisplayAmount(it, currencyDisplay),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun RecurringPendingRowTexts(
    model: RecurringPendingRowModel,
    intentState: RecurringPendingState,
    currencyDisplay: CurrencyDisplay,
) {
    val stateColor = if (intentState == RecurringPendingState.WAITING) {
        MaterialTheme.colorScheme.onSurfaceVariant
    } else {
        LocalStateTokens.current.warn.fg
    }
    Text(
        text = model.title ?: stringResource(model.titleFallbackRes),
        style = MaterialTheme.typography.bodyMedium,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
    Text(
        text = stringResource(
            R.string.recurring_pending_kind_state,
            stringResource(model.kindLabelRes),
            stringResource(model.stateLabelRes),
        ),
        color = stateColor,
        style = MaterialTheme.typography.bodySmall,
    )
    if (model.changes.isNotEmpty()) {
        val changeTexts = model.changes.map { change -> recurringPendingChangeText(change, currencyDisplay) }
        Text(
            text = changeTexts.joinToString(" · "),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
    model.stateGuidanceRes?.let {
        Text(
            text = stringResource(it),
            color = stateColor,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun recurringPendingChangeText(
    change: RecurringPendingChange,
    currencyDisplay: CurrencyDisplay,
): String = when (change) {
    is RecurringPendingChange.MerchantTo -> stringResource(
        R.string.recurring_pending_change_merchant,
        change.value,
    )
    is RecurringPendingChange.AmountTo -> stringResource(
        R.string.recurring_pending_change_amount,
        formatDisplayAmount(change.cents, currencyDisplay),
    )
    is RecurringPendingChange.DateTo -> stringResource(
        R.string.recurring_pending_change_date,
        recurringDisplayDate(change.iso),
    )
    RecurringPendingChange.DateCleared -> stringResource(
        R.string.recurring_pending_change_date_cleared,
    )
}

@Composable
internal fun RecurringConflictBanner(
    model: RecurringConflictModel,
    onAction: (RecurringConflictModel) -> Unit,
) {
    AppSectionGroup(
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        RecurringConflictCopy(model = model, titleStyle = MaterialTheme.typography.titleMedium)
        RecurringConflictActionButton(model = model, onAction = onAction)
    }
}

/** 表单内的同款冲突块：创建/编辑撞单时直接给出出口，而不是只亮校验错。 */
@Composable
internal fun RecurringConflictBlock(
    model: RecurringConflictModel,
    onAction: (RecurringConflictModel) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        RecurringConflictCopy(model = model, titleStyle = MaterialTheme.typography.titleSmall)
        RecurringConflictActionButton(model = model, onAction = onAction)
    }
}

@Composable
private fun RecurringConflictCopy(
    model: RecurringConflictModel,
    titleStyle: androidx.compose.ui.text.TextStyle,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = stringResource(R.string.recurring_conflict_title),
            style = titleStyle,
            fontWeight = AppTextHierarchy.heading.weight,
            color = LocalStateTokens.current.warn.fg,
        )
        Text(
            text = model.merchant?.let { stringResource(R.string.recurring_conflict_body, it) }
                ?: stringResource(R.string.recurring_conflict_body_unknown),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun RecurringConflictActionButton(
    model: RecurringConflictModel,
    onAction: (RecurringConflictModel) -> Unit,
) {
    val labelRes = when (model.action) {
        RecurringConflictAction.EditExisting -> R.string.recurring_conflict_action_edit
        RecurringConflictAction.RestoreArchived -> R.string.recurring_conflict_action_restore
        RecurringConflictAction.Unavailable -> return
    }
    AppSecondaryButton(
        text = stringResource(labelRes),
        onClick = { onAction(model) },
    )
}
