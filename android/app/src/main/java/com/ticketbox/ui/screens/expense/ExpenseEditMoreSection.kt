package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppSolidCard

// Stable test tags for the 「更多记录」inputs — instrumented tests target these instead of the
// Material3 label/value text (not reliably in the semantics tree). Shared constants so the UI and
// ExpenseEditScreenContractTest never drift on a magic string.
internal const val TAG_TAGS_FIELD = "expense-edit-tags-field"
internal const val TAG_VALUE_SCORE_FIELD = "expense-edit-value-score-field"
internal const val TAG_REGRET_SCORE_FIELD = "expense-edit-regret-score-field"

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
    // ADR-0042: retry-OCR and paste-text-recognize are pending-only server-side
    // (404 on a confirmed/rejected row). Gate the affordances so a non-pending
    // expense never offers them — online it 404s, offline it queues a mutation
    // that the dispatcher discards on replay.
    canRecognize: Boolean = false,
    onRetryOcr: () -> Unit,
    onRecognizeText: () -> Unit = {},
) {
    AppSolidCard {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(stringResource(R.string.expense_edit_more_title), style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = stringResource(R.string.expense_edit_more_subtitle),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                AppOutlinedButton(onClick = onToggleMore) {
                    Text(
                        if (moreExpanded) {
                            stringResource(R.string.expense_edit_more_collapse_button)
                        } else {
                            stringResource(R.string.expense_edit_more_expand_button)
                        }
                    )
                }
            }

            if (moreExpanded) {
                // testTag: instrumented tests locate these by a stable tag, not a Material3
                // OutlinedTextField label/value text node (which isn't reliably exposed in the
                // semantics tree — the cause of ExpenseEditScreenContractTest's flaky "标签" lookup).
                OutlinedTextField(
                    value = tags,
                    onValueChange = onTagsChange,
                    modifier = Modifier.fillMaxWidth().testTag(TAG_TAGS_FIELD),
                    label = { Text(stringResource(R.string.expense_edit_more_tags_label)) },
                    placeholder = { Text(stringResource(R.string.expense_edit_more_tags_placeholder)) },
                    enabled = !readOnly,
                )
                OutlinedTextField(
                    value = valueScoreText,
                    onValueChange = onValueScoreChange,
                    modifier = Modifier.fillMaxWidth().testTag(TAG_VALUE_SCORE_FIELD),
                    label = { Text(stringResource(R.string.expense_edit_more_value_score_label)) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    enabled = !readOnly,
                )
                OutlinedTextField(
                    value = regretScoreText,
                    onValueChange = onRegretScoreChange,
                    modifier = Modifier.fillMaxWidth().testTag(TAG_REGRET_SCORE_FIELD),
                    label = { Text(stringResource(R.string.expense_edit_more_regret_score_label)) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    enabled = !readOnly,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = onToggleRawText) {
                        Text(
                            if (rawTextExpanded) {
                                stringResource(R.string.expense_edit_more_raw_text_collapse_button)
                            } else {
                                stringResource(R.string.expense_edit_more_raw_text_expand_button)
                            }
                        )
                    }
                    if (!readOnly && canRecognize) {
                        AppOutlinedButton(
                            enabled = !ocrRunning && !saving,
                            onClick = onRetryOcr,
                        ) {
                            Text(
                                if (ocrRunning) {
                                    stringResource(R.string.expense_edit_more_recognize_running_button)
                                } else {
                                    stringResource(R.string.expense_edit_more_recognize_retry_button)
                                }
                            )
                        }
                        // ADR-0042 Slice E-2: paste the receipt text by hand and
                        // let the server parse it into the empty fields (distinct
                        // from re-running OCR on the stored image).
                        AppOutlinedButton(
                            enabled = !ocrRunning && !saving,
                            onClick = onRecognizeText,
                        ) {
                            Text(stringResource(R.string.expense_edit_more_recognize_paste_button))
                        }
                    }
                }
                if (rawTextExpanded) {
                    Text(
                        stringResource(R.string.expense_edit_more_raw_text_value, rawTextDisplay),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}
