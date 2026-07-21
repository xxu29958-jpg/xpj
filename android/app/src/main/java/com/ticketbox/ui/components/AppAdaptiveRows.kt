package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing

@Immutable
data class AppAdaptiveFieldPairWeights(
    val leading: Float = 1f,
    val trailing: Float = 1f,
)

@Immutable
data class AppAdaptiveAmountRowStyle(
    val role: AppAmountRole = AppAmountRole.Compact,
    val amountColor: Color? = null,
    val trailingWeight: Float = AppAdaptiveAmountRowDefaults.trailingWeight,
)

object AppAdaptiveAmountRowDefaults {
    val trailingWeight: Float = 0.44f
    val reviewTrailingWeight: Float = 0.62f
    val listTrailingWeight: Float = 0.68f
    val groupHeaderTrailingWeight: Float = 0.42f
    val reconciliationTrailingWeight: Float = 0.72f
    val statusMinWidth: Dp = 118.dp
    val secondaryMetaInlineMaxWidth: Dp = 132.dp
}

enum class AppAdaptiveEditActionMode {
    Stacked,
    Compact,
    Inline,
}

internal enum class AppAdaptiveContentActionMode {
    Stacked,
    Inline,
}

internal enum class AppAdaptiveAmountRowMode {
    Stacked,
    Inline,
}

internal enum class AppAdaptiveStatusContentMode {
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
        when (
            resolveAppAdaptiveContentActionMode(
                maxWidth = maxWidth,
                fontScale = LocalDensity.current.fontScale,
            )
        ) {
            AppAdaptiveContentActionMode.Stacked -> {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                ) {
                    content()
                    action(Modifier.fillMaxWidth(), true)
                }
            }
            AppAdaptiveContentActionMode.Inline -> {
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
}

internal fun resolveAppAdaptiveContentActionMode(
    maxWidth: Dp,
    fontScale: Float = 1f,
): AppAdaptiveContentActionMode =
    if (maxWidth / fontScale.coerceAtLeast(1f) < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
        AppAdaptiveContentActionMode.Stacked
    } else {
        AppAdaptiveContentActionMode.Inline
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
    style: AppAdaptiveAmountRowStyle = AppAdaptiveAmountRowStyle(),
    content: @Composable () -> Unit,
) {
    val amountColor = style.amountColor ?: MaterialTheme.colorScheme.onSurface
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
                    role = style.role,
                    color = amountColor,
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
                    modifier = Modifier.weight(style.trailingWeight),
                    text = amount,
                    role = style.role,
                    color = amountColor,
                )
            }
        }
    }
}

internal fun resolveAppAdaptiveAmountRowMode(maxWidth: Dp): AppAdaptiveAmountRowMode =
    if (maxWidth < AppAdaptiveBreakpoints.amountRowInlineMinWidth) {
        AppAdaptiveAmountRowMode.Stacked
    } else {
        AppAdaptiveAmountRowMode.Inline
    }

@Composable
fun AppAdaptiveStatusContentRow(
    modifier: Modifier = Modifier,
    statusMinWidth: Dp = AppAdaptiveAmountRowDefaults.statusMinWidth,
    status: @Composable () -> Unit,
    content: @Composable () -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        when (resolveAppAdaptiveStatusContentMode(maxWidth)) {
            AppAdaptiveStatusContentMode.Stacked -> Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                status()
                content()
            }
            AppAdaptiveStatusContentMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                verticalAlignment = Alignment.Top,
            ) {
                Box(
                    modifier = Modifier.widthIn(min = statusMinWidth),
                    contentAlignment = Alignment.TopStart,
                ) {
                    status()
                }
                Box(modifier = Modifier.weight(1f)) {
                    content()
                }
            }
        }
    }
}

internal fun resolveAppAdaptiveStatusContentMode(maxWidth: Dp): AppAdaptiveStatusContentMode =
    if (maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
        AppAdaptiveStatusContentMode.Stacked
    } else {
        AppAdaptiveStatusContentMode.Inline
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
