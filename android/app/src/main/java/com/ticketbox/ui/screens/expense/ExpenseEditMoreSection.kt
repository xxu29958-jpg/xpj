package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.design.AppSpacing

internal const val TAG_TAGS_FIELD = "expense-edit-tags-field"
internal const val TAG_VALUE_SCORE_FIELD = "expense-edit-value-score-field"
internal const val TAG_REGRET_SCORE_FIELD = "expense-edit-regret-score-field"

private data class MoreExpandedState(
    val tags: String,
    val valueScoreText: String,
    val regretScoreText: String,
    val valueScoreBaseline: Int?,
    val regretScoreBaseline: Int?,
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
    val onValueScoreUndo: () -> Unit,
    val onRegretScoreUndo: () -> Unit,
    val onToggleRawText: () -> Unit,
    val onRetryOcr: () -> Unit,
    val onRecognizeText: () -> Unit,
)

@Immutable
internal data class ExpenseEditMoreSectionState(
    val tags: String,
    val valueScoreText: String,
    val regretScoreText: String,
    val valueScoreBaseline: Int?,
    val regretScoreBaseline: Int?,
    val rawTextDisplay: String,
    val moreExpanded: Boolean,
    val rawTextExpanded: Boolean,
    val ocrRunning: Boolean,
    val saving: Boolean,
    val readOnly: Boolean = false,
    val canRecognize: Boolean = false,
)

@Immutable
internal data class ExpenseEditMoreSectionActions(
    val onTagsChange: (String) -> Unit,
    val onValueScoreChange: (String) -> Unit,
    val onRegretScoreChange: (String) -> Unit,
    val onValueScoreUndo: () -> Unit,
    val onRegretScoreUndo: () -> Unit,
    val onToggleMore: () -> Unit,
    val onToggleRawText: () -> Unit,
    val onRetryOcr: () -> Unit,
    val onRecognizeText: () -> Unit = {},
)

@Composable
internal fun ExpenseEditMoreSection(
    state: ExpenseEditMoreSectionState,
    actions: ExpenseEditMoreSectionActions,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ExpenseEditMoreHeader(
            moreExpanded = state.moreExpanded,
            onToggleMore = actions.onToggleMore,
        )

        if (state.moreExpanded) {
            ExpenseEditMoreExpandedFields(
                state = MoreExpandedState(
                    tags = state.tags,
                    valueScoreText = state.valueScoreText,
                    regretScoreText = state.regretScoreText,
                    valueScoreBaseline = state.valueScoreBaseline,
                    regretScoreBaseline = state.regretScoreBaseline,
                    rawTextDisplay = state.rawTextDisplay,
                    rawTextExpanded = state.rawTextExpanded,
                    ocrRunning = state.ocrRunning,
                    saving = state.saving,
                    readOnly = state.readOnly,
                    canRecognize = state.canRecognize,
                ),
                actions = MoreExpandedActions(
                    onTagsChange = actions.onTagsChange,
                    onValueScoreChange = actions.onValueScoreChange,
                    onRegretScoreChange = actions.onRegretScoreChange,
                    onValueScoreUndo = actions.onValueScoreUndo,
                    onRegretScoreUndo = actions.onRegretScoreUndo,
                    onToggleRawText = actions.onToggleRawText,
                    onRetryOcr = actions.onRetryOcr,
                    onRecognizeText = actions.onRecognizeText,
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
    AppAdaptiveContentActionRow(
        modifier = Modifier.fillMaxWidth(),
        content = {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(stringResource(R.string.expense_edit_more_title), style = MaterialTheme.typography.titleSmall)
                Text(
                    text = stringResource(R.string.expense_edit_more_subtitle),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        },
        action = { actionModifier ->
            QuietOutlinedButton(
                text = if (moreExpanded) {
                    stringResource(R.string.expense_edit_more_collapse_button)
                } else {
                    stringResource(R.string.expense_edit_more_expand_button)
                },
                modifier = actionModifier,
                onClick = onToggleMore,
            )
        },
    )
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
            modifier = Modifier.fillMaxWidth(),
            fieldModifier = Modifier.testTag(TAG_TAGS_FIELD),
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
    // 1-5 点选 chip：点选即改值。不做「再点取消」也不做「清除」——空值提交是
    // exclude_unset 的「保持原值」，没有清除已存评分的命令。草稿改离已存值时
    // 出「撤销修改」，点即回到已存值（已存为空则回到未选）。
    ExpenseEditScoreChipRow(
        model = ScoreChipRowModel(
            label = stringResource(R.string.expense_edit_more_value_score_short_label),
            valueText = state.valueScoreText,
            baselineScore = state.valueScoreBaseline,
            enabled = !state.readOnly,
            testTag = TAG_VALUE_SCORE_FIELD,
        ),
        onSelect = actions.onValueScoreChange,
        onUndo = actions.onValueScoreUndo,
    )
    ExpenseEditScoreChipRow(
        model = ScoreChipRowModel(
            label = stringResource(R.string.expense_edit_more_regret_score_short_label),
            valueText = state.regretScoreText,
            baselineScore = state.regretScoreBaseline,
            enabled = !state.readOnly,
            testTag = TAG_REGRET_SCORE_FIELD,
        ),
        onSelect = actions.onRegretScoreChange,
        onUndo = actions.onRegretScoreUndo,
    )
}

/** 评分「撤销修改」可见性：草稿文本与已存值不同才算本场改动；空串与 null 同义。 */
internal fun expenseEditScoreModifiedSinceBaseline(currentText: String, baselineScore: Int?): Boolean =
    currentText != baselineScore?.toString().orEmpty()

private data class ScoreChipRowModel(
    val label: String,
    val valueText: String,
    val baselineScore: Int?,
    val enabled: Boolean,
    val testTag: String,
)

@Composable
private fun ExpenseEditScoreChipRow(
    model: ScoreChipRowModel,
    onSelect: (String) -> Unit,
    onUndo: () -> Unit,
) {
    val selectedScore = model.valueText.toIntOrNull()
    val modified = expenseEditScoreModifiedSinceBaseline(model.valueText, model.baselineScore)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .testTag(model.testTag),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = model.label,
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
            )
            if (model.enabled && modified) {
                QuietOutlinedButton(
                    text = stringResource(R.string.expense_edit_undo_change_button),
                    onClick = onUndo,
                )
            }
        }
        AppCompactChips {
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
                (1..5).forEach { score ->
                    SelectableCategoryChip(
                        selected = selectedScore == score,
                        label = score.toString(),
                        enabled = model.enabled,
                        onClick = { onSelect(score.toString()) },
                    )
                }
            }
        }
    }
}

@Composable
private fun ExpenseEditMoreOcrActions(
    state: MoreExpandedState,
    actions: MoreExpandedActions,
) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        QuietOutlinedButton(
            text = if (state.rawTextExpanded) {
                stringResource(R.string.expense_edit_more_raw_text_collapse_button)
            } else {
                stringResource(R.string.expense_edit_more_raw_text_expand_button)
            },
            onClick = actions.onToggleRawText,
        )
        if (!state.readOnly && state.canRecognize) {
            QuietOutlinedButton(
                text = if (state.ocrRunning) {
                    stringResource(R.string.expense_edit_more_recognize_running_button)
                } else {
                    stringResource(R.string.expense_edit_more_recognize_retry_button)
                },
                enabled = !state.ocrRunning && !state.saving,
                onClick = actions.onRetryOcr,
            )
        }
    }
    if (!state.readOnly && state.canRecognize) {
        QuietOutlinedButton(
            text = stringResource(R.string.expense_edit_more_recognize_paste_button),
            modifier = Modifier.fillMaxWidth(),
            enabled = !state.ocrRunning && !state.saving,
            onClick = actions.onRecognizeText,
        )
    }
}
