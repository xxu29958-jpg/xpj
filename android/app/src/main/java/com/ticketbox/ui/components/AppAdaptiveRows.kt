package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing

private const val ADAPTIVE_AMOUNT_ROW_TRAILING_WEIGHT = 0.44f

@Immutable
data class AppAdaptiveFieldPairWeights(
    val leading: Float = 1f,
    val trailing: Float = 1f,
)

enum class AppAdaptiveEditActionMode {
    Stacked,
    Compact,
    Inline,
}

internal enum class AppAdaptiveAmountRowMode {
    Stacked,
    Inline,
}

@Composable
fun AppAdaptiveContentActionRow(
    modifier: Modifier = Modifier,
    wideActionWeight: Float? = null,
    verticalAlignment: Alignment.Vertical = Alignment.CenterVertically,
    content: @Composable () -> Unit,
    action: @Composable (Modifier) -> Unit,
) {
    AppAdaptiveContentActionStateRow(
        modifier = modifier,
        wideActionWeight = wideActionWeight,
        verticalAlignment = verticalAlignment,
        content = content,
    ) { actionModifier, _ ->
        action(actionModifier)
    }
}

@Composable
fun AppAdaptiveContentActionStateRow(
    modifier: Modifier = Modifier,
    wideActionWeight: Float? = null,
    verticalAlignment: Alignment.Vertical = Alignment.CenterVertically,
    content: @Composable () -> Unit,
    action: @Composable (Modifier, Boolean) -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        if (maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                content()
                action(Modifier.fillMaxWidth(), true)
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                verticalAlignment = verticalAlignment,
            ) {
                Box(modifier = Modifier.weight(1f)) {
                    content()
                }
                action(wideActionWeight?.let { Modifier.weight(it) } ?: Modifier, false)
            }
        }
    }
}

@Composable
fun AppAdaptiveEditActionLayout(
    actionCount: Int,
    compact: Boolean,
    modifier: Modifier = Modifier,
    stackTwoActionsOnNarrow: Boolean = false,
    content: @Composable (AppAdaptiveEditActionMode) -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        val mode = resolveAppAdaptiveEditActionMode(
            maxWidth = maxWidth,
            actionCount = actionCount,
            compact = compact,
            stackTwoActionsOnNarrow = stackTwoActionsOnNarrow,
        )
        content(mode)
    }
}

internal fun resolveAppAdaptiveEditActionMode(
    maxWidth: Dp,
    actionCount: Int,
    compact: Boolean,
    stackTwoActionsOnNarrow: Boolean = false,
): AppAdaptiveEditActionMode = when {
    maxWidth < AppAdaptiveBreakpoints.editActionInlineMinWidth &&
        (actionCount >= 3 || stackTwoActionsOnNarrow && actionCount >= 2) ->
        AppAdaptiveEditActionMode.Stacked
    compact -> AppAdaptiveEditActionMode.Compact
    else -> AppAdaptiveEditActionMode.Inline
}

@Composable
fun AppAdaptiveEditAmountRow(
    amount: String,
    modifier: Modifier = Modifier,
    role: AppAmountRole = AppAmountRole.Compact,
    content: @Composable () -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        when (resolveAppAdaptiveAmountRowMode(maxWidth)) {
            AppAdaptiveAmountRowMode.Stacked -> Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                content()
                AppEndAlignedAmountText(
                    modifier = Modifier.fillMaxWidth(),
                    text = amount,
                    role = role,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            AppAdaptiveAmountRowMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                verticalAlignment = Alignment.Top,
            ) {
                Box(modifier = Modifier.weight(1f)) {
                    content()
                }
                AppEndAlignedAmountText(
                    modifier = Modifier.weight(ADAPTIVE_AMOUNT_ROW_TRAILING_WEIGHT),
                    text = amount,
                    role = role,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

internal fun resolveAppAdaptiveAmountRowMode(maxWidth: Dp): AppAdaptiveAmountRowMode =
    if (maxWidth < AppAdaptiveBreakpoints.editActionInlineMinWidth) {
        AppAdaptiveAmountRowMode.Stacked
    } else {
        AppAdaptiveAmountRowMode.Inline
    }

@Composable
fun AppAdaptiveFieldPairRow(
    modifier: Modifier = Modifier,
    weights: AppAdaptiveFieldPairWeights = AppAdaptiveFieldPairWeights(),
    leading: @Composable (Modifier) -> Unit,
    trailing: @Composable (Modifier) -> Unit,
    action: @Composable () -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        if (maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    leading(Modifier.weight(1f))
                    action()
                }
                trailing(Modifier.fillMaxWidth())
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                leading(Modifier.weight(weights.leading))
                trailing(Modifier.weight(weights.trailing))
                action()
            }
        }
    }
}

@Composable
fun AppAdaptiveTrailingActionRow(
    modifier: Modifier = Modifier,
    action: @Composable (Modifier) -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        val actionModifier = if (maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
            Modifier.fillMaxWidth()
        } else {
            Modifier.align(Alignment.CenterEnd)
        }
        action(actionModifier)
    }
}
