package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.design.AppSpacing

internal const val TAG_TAGS_FIELD = "expense-edit-tags-field"
internal const val TAG_VALUE_SCORE_FIELD = "expense-edit-value-score-field"
internal const val TAG_REGRET_SCORE_FIELD = "expense-edit-regret-score-field"

private data class MoreExpandedState(
    val tags: String,
    val valueScoreText: String,
    val regretScoreText: String,
    val rawTextDisplay: String,
    val rawTextExpanded: Boolean,
    val ocrRunning: Boolean,
    val saving: Boolean,
    val readOnly: Boolean,
    val canRecognize: Boolean,
)

private data class MoreExpandedActions(
    val onTagsChange: (String) -> Unit,
    val onValueScoreChange: (String) -> Unit,
    val onRegretScoreChange: (String) -> Unit,
    val onToggleRawText: () -> Unit,
    val onRetryOcr: () -> Unit,
    val onRecognizeText: () -> Unit,
)

@Composable
internal fun ExpenseEditMoreSection(
    tags: String,
    onTagsChange: (String) -> Unit,
    valueScoreText: String,
    onValueScoreChange: (String) -> Unit,
    regretScoreText: String,
    onRegretScoreChange: (String) -> Unit,
    rawTextDisplay: String,
    moreExpanded: Boolean,
    onToggleMore: () -> Unit,
    rawTextExpanded: Boolean,
    onToggleRawText: () -> Unit,
    ocrRunning: Boolean,
    saving: Boolean,
    readOnly: Boolean = false,
    canRecognize: Boolean = false,
    onRetryOcr: () -> Unit,
    onRecognizeText: () -> Unit = {},
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ExpenseEditMoreHeader(
            moreExpanded = moreExpanded,
            onToggleMore = onToggleMore,
        )

        if (moreExpanded) {
            ExpenseEditMoreExpandedFields(
                state = MoreExpandedState(
                    tags = tags,
                    valueScoreText = valueScoreText,
                    regretScoreText = regretScoreText,
                    rawTextDisplay = rawTextDisplay,
                    rawTextExpanded = rawTextExpanded,
                    ocrRunning = ocrRunning,
                    saving = saving,
                    readOnly = readOnly,
                    canRecognize = canRecognize,
                ),
                actions = MoreExpandedActions(
                    onTagsChange = onTagsChange,
                    onValueScoreChange = onValueScoreChange,
                    onRegretScoreChange = onRegretScoreChange,
                    onToggleRawText = onToggleRawText,
                    onRetryOcr = onRetryOcr,
                    onRecognizeText = onRecognizeText,
                ),
            )
        }
    }
}

@Composable
private fun ExpenseEditMoreHeader(
    moreExpanded: Boolean,
    onToggleMore: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(stringResource(R.string.expense_edit_more_title), style = MaterialTheme.typography.titleSmall)
            Text(
                text = stringResource(R.string.expense_edit_more_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        TextButton(onClick = onToggleMore) {
            Text(
                if (moreExpanded) {
                    stringResource(R.string.expense_edit_more_collapse_button)
                } else {
                    stringResource(R.string.expense_edit_more_expand_button)
                },
            )
        }
    }
}

@Composable
private fun ExpenseEditMoreExpandedFields(
    state: MoreExpandedState,
    actions: MoreExpandedActions,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        ExpenseEditTextField(
            state = ExpenseEditTextFieldState(
                label = stringResource(R.string.expense_edit_more_tags_label),
                value = state.tags,
                placeholder = stringResource(R.string.expense_edit_more_tags_placeholder),
                enabled = !state.readOnly,
            ),
            onValueChange = actions.onTagsChange,
            modifier = Modifier.fillMaxWidth().testTag(TAG_TAGS_FIELD),
        )
        ExpenseEditScoreFields(
            state = state,
            actions = actions,
        )
        ExpenseEditMoreOcrActions(
            state = state,
            actions = actions,
        )
        if (state.rawTextExpanded) {
            Text(
                stringResource(R.string.expense_edit_more_raw_text_value, state.rawTextDisplay),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ExpenseEditScoreFields(
    state: MoreExpandedState,
    actions: MoreExpandedActions,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        ExpenseEditTextField(
            state = ExpenseEditTextFieldState(
                label = stringResource(R.string.expense_edit_more_value_score_short_label),
                value = state.valueScoreText,
                placeholder = stringResource(R.string.expense_edit_more_score_placeholder),
                enabled = !state.readOnly,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            ),
            onValueChange = actions.onValueScoreChange,
            modifier = Modifier.weight(1f).testTag(TAG_VALUE_SCORE_FIELD),
        )
        ExpenseEditTextField(
            state = ExpenseEditTextFieldState(
                label = stringResource(R.string.expense_edit_more_regret_score_short_label),
                value = state.regretScoreText,
                placeholder = stringResource(R.string.expense_edit_more_score_placeholder),
                enabled = !state.readOnly,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            ),
            onValueChange = actions.onRegretScoreChange,
            modifier = Modifier.weight(1f).testTag(TAG_REGRET_SCORE_FIELD),
        )
    }
}

@Composable
private fun ExpenseEditMoreOcrActions(
    state: MoreExpandedState,
    actions: MoreExpandedActions,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        TextButton(onClick = actions.onToggleRawText) {
            Text(
                if (state.rawTextExpanded) {
                    stringResource(R.string.expense_edit_more_raw_text_collapse_button)
                } else {
                    stringResource(R.string.expense_edit_more_raw_text_expand_button)
                },
            )
        }
        if (!state.readOnly && state.canRecognize) {
            AppOutlinedButton(
                modifier = Modifier.weight(1f),
                enabled = !state.ocrRunning && !state.saving,
                onClick = actions.onRetryOcr,
            ) {
                Text(
                    if (state.ocrRunning) {
                        stringResource(R.string.expense_edit_more_recognize_running_button)
                    } else {
                        stringResource(R.string.expense_edit_more_recognize_retry_button)
                    },
                )
            }
        }
    }
    if (!state.readOnly && state.canRecognize) {
        AppOutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            enabled = !state.ocrRunning && !state.saving,
            onClick = actions.onRecognizeText,
        ) {
            Text(stringResource(R.string.expense_edit_more_recognize_paste_button))
        }
    }
}
