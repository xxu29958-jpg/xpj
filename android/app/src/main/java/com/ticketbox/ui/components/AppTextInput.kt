package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.FocusState
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

@Immutable
data class AppTextInputState(
    val label: String,
    val value: String,
    val placeholder: String = "",
    val trailingLabel: String? = null,
    val enabled: Boolean = true,
    val singleLine: Boolean = true,
    val minLines: Int = 1,
    val maxLines: Int = 3,
    val isError: Boolean = false,
    val emphasis: AppTextInputEmphasis = AppTextInputEmphasis.Standard,
    val keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
)

enum class AppTextInputEmphasis {
    Standard,
    Amount,
}

data class AppTextInputActions(
    val onValueChange: (String) -> Unit,
    val onFocusChanged: (FocusState) -> Unit = {},
    val keyboardActions: KeyboardActions = KeyboardActions.Default,
)

data class AppTextInputDecorations(
    val leadingContent: (@Composable () -> Unit)? = null,
    val trailingContent: (@Composable () -> Unit)? = null,
    val supportingText: (@Composable () -> Unit)? = null,
)

@Composable
fun AppTextInput(
    state: AppTextInputState,
    actions: AppTextInputActions,
    modifier: Modifier = Modifier,
    focusRequester: FocusRequester? = null,
    decorations: AppTextInputDecorations = AppTextInputDecorations(),
) {
    var focused by remember { mutableStateOf(false) }
    val focusState = AppTextInputFocusState(
        focused = focused,
        onFocusChanged = {
            focused = it.isFocused
            actions.onFocusChanged(it)
        },
    )
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        AppTextInputHeader(state)
        AppTextInputField(
            state = state,
            actions = actions,
            focusRequester = focusRequester,
            focusState = focusState,
            decorations = decorations,
        )
        decorations.supportingText?.invoke()
    }
}

private data class AppTextInputFocusState(
    val focused: Boolean,
    val onFocusChanged: (FocusState) -> Unit,
)

@Composable
private fun AppTextInputHeader(state: AppTextInputState) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = state.label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.body.weight,
        )
        state.trailingLabel?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.strong),
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun AppTextInputField(
    state: AppTextInputState,
    actions: AppTextInputActions,
    focusRequester: FocusRequester?,
    focusState: AppTextInputFocusState,
    decorations: AppTextInputDecorations,
) {
    BasicTextField(
        value = state.value,
        onValueChange = actions.onValueChange,
        modifier = Modifier
            .fillMaxWidth()
            .then(if (focusRequester != null) Modifier.focusRequester(focusRequester) else Modifier)
            .onFocusChanged(focusState.onFocusChanged),
        enabled = state.enabled,
        singleLine = state.singleLine,
        minLines = if (state.singleLine) 1 else state.minLines,
        maxLines = if (state.singleLine) 1 else state.maxLines,
        keyboardOptions = state.keyboardOptions,
        keyboardActions = actions.keyboardActions,
        textStyle = appTextInputTextStyle(state),
        decorationBox = { innerTextField ->
            AppTextInputFrame(state = state, focused = focusState.focused, decorations = decorations) {
                val showPlaceholder = state.value.isEmpty() &&
                    state.placeholder.isNotBlank() &&
                    !(focusState.focused && state.emphasis == AppTextInputEmphasis.Amount)
                if (showPlaceholder) {
                    Text(
                        text = state.placeholder,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.medium),
                        style = if (state.emphasis == AppTextInputEmphasis.Amount) {
                            MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium)
                        } else {
                            appTextInputTextStyle(state)
                        },
                    )
                }
                innerTextField()
            }
        },
    )
}

@Composable
private fun AppTextInputFrame(
    state: AppTextInputState,
    focused: Boolean,
    decorations: AppTextInputDecorations,
    content: @Composable () -> Unit,
) {
    val shape = RoundedCornerShape(AppRadius.extraSmall)
    val verticalPadding = if (state.singleLine) AppSpacing.contentGap else AppSpacing.compactGap
    val borderColor = appTextInputBorderColor(state, focused)
    val baseModifier = Modifier
        .fillMaxWidth()
        .heightIn(min = appTextInputMinHeight(state))
        .clip(shape)
        .background(appTextInputBackgroundColor(state))
    val framedModifier = if (state.emphasis == AppTextInputEmphasis.Amount) {
        baseModifier.drawBehind {
            val stroke = 1.dp.toPx()
            val y = size.height - stroke / 2
            drawLine(color = borderColor, start = Offset(0f, y), end = Offset(size.width, y), strokeWidth = stroke)
        }
    } else {
        baseModifier.border(1.dp, borderColor, shape)
    }
    val contentAlignment = if (state.singleLine) Alignment.CenterStart else Alignment.TopStart
    val contentModifier = framedModifier
        .padding(horizontal = AppSpacing.cardPaddingTight, vertical = verticalPadding)
    if (decorations.leadingContent == null && decorations.trailingContent == null) {
        Box(
            modifier = contentModifier,
            contentAlignment = contentAlignment,
        ) {
            content()
        }
    } else {
        Row(
            modifier = contentModifier,
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = if (state.singleLine) Alignment.CenterVertically else Alignment.Top,
        ) {
            decorations.leadingContent?.invoke()
            Box(
                modifier = Modifier.weight(1f),
                contentAlignment = contentAlignment,
            ) {
                content()
            }
            decorations.trailingContent?.invoke()
        }
    }
}

private fun appTextInputMinHeight(state: AppTextInputState) = when {
    state.emphasis == AppTextInputEmphasis.Amount -> AppSpacing.controlMinHeight + AppSpacing.compactGap
    state.singleLine -> AppSpacing.controlMinHeight + AppSpacing.miniGap
    else -> (AppSpacing.controlMinHeight * state.minLines.toFloat()) + AppSpacing.compactGap
}

@Composable
private fun appTextInputBorderColor(state: AppTextInputState, focused: Boolean): Color {
    val visuals = LocalThemeVisuals.current
    return when {
        state.isError -> MaterialTheme.colorScheme.error.copy(alpha = AppAlpha.heavy)
        focused -> visuals.focusRing.copy(alpha = AppAlpha.heavy)
        else -> MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft)
    }
}

@Composable
private fun appTextInputBackgroundColor(state: AppTextInputState): Color {
    val visuals = LocalThemeVisuals.current
    if (state.emphasis == AppTextInputEmphasis.Amount && state.enabled) return Color.Transparent
    return if (state.enabled) {
        visuals.surfaceSunken.copy(alpha = AppAlpha.faint)
    } else {
        visuals.surfaceSunken.copy(alpha = AppAlpha.soft)
    }
}

@Composable
private fun appTextInputTextStyle(state: AppTextInputState): TextStyle {
    val color = if (state.enabled) {
        MaterialTheme.colorScheme.onSurface
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.strong)
    }
    return when (state.emphasis) {
        AppTextInputEmphasis.Amount -> MaterialTheme.typography.headlineSmall
            .copy(color = color, fontWeight = FontWeight.SemiBold)
            .tabularNum()
        AppTextInputEmphasis.Standard -> MaterialTheme.typography.bodyLarge.copy(color = color)
    }
}
