package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.SoftPanel

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
    onRetryOcr: () -> Unit,
) {
    SoftPanel(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text("更多记录", style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = "标签、值不值、后悔指数和识别原文",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                OutlinedButton(onClick = onToggleMore) {
                    Text(if (moreExpanded) "收起" else "展开")
                }
            }

            if (moreExpanded) {
                OutlinedTextField(
                    value = tags,
                    onValueChange = onTagsChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("标签") },
                    placeholder = { Text("真香、必要支出") },
                    enabled = !readOnly,
                )
                OutlinedTextField(
                    value = valueScoreText,
                    onValueChange = onValueScoreChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("值不值评分，1-5") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    enabled = !readOnly,
                )
                OutlinedTextField(
                    value = regretScoreText,
                    onValueChange = onRegretScoreChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("后悔指数，1-5") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    enabled = !readOnly,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = onToggleRawText) {
                        Text(if (rawTextExpanded) "收起识别原文" else "查看识别原文")
                    }
                    if (!readOnly) {
                        OutlinedButton(
                            enabled = !ocrRunning && !saving,
                            onClick = onRetryOcr,
                        ) {
                            Text(if (ocrRunning) "识别中" else "重新识别")
                        }
                    }
                }
                if (rawTextExpanded) {
                    Text("识别原文：$rawTextDisplay", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
