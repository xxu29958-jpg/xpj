package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.ExpenseImagePreview
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatAmount

@Composable
internal fun EditDraftPreviewCard(
    expense: Expense,
    previewImage: ProtectedImage?,
    imageLoading: Boolean,
    ocrRunning: Boolean,
    showLargeImage: Boolean,
    onToggleLargeImage: () -> Unit,
    onRetryOcr: () -> Unit,
) {
    SoftPanel(containerAlpha = 0.98f) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (expense.imagePath != null) {
                ExpenseImagePreview(
                    image = previewImage,
                    placeholder = if (imageLoading) "截图加载中" else "截图已保存",
                    compact = true,
                    compactSize = DpSize(width = 104.dp, height = 136.dp),
                )
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(7.dp),
            ) {
                Text(
                    text = "识别草稿",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelLarge,
                )
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: "待填写商家",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = formatAmount(expense.amountCents),
                    style = MaterialTheme.typography.headlineMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    StatusPill(expense.category)
                    expense.confidence?.let {
                        StatusPill("可信度 ${(it * 100).toInt()}%", active = false)
                    }
                }
                if (expense.imagePath != null) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            modifier = Modifier
                                .weight(0.82f)
                                .height(40.dp),
                            enabled = !imageLoading,
                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                            onClick = onToggleLargeImage,
                        ) {
                            Text(
                                when {
                                    imageLoading -> "加载中"
                                    showLargeImage -> "收起截图"
                                    else -> "看原图"
                                },
                                maxLines = 1,
                                softWrap = false,
                                overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        OutlinedButton(
                            modifier = Modifier
                                .weight(1f)
                                .height(40.dp),
                            enabled = !ocrRunning,
                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                            onClick = onRetryOcr,
                        ) {
                            Text(
                                if (ocrRunning) "识别中" else "重新识别",
                                maxLines = 1,
                                softWrap = false,
                                overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun OcrProgressCard() {
    SoftPanel(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "正在重新识别截图",
                style = MaterialTheme.typography.titleMedium,
            )
            Text(
                text = "识别结果只会更新草稿，仍需要你核对后确认入账。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
internal fun SelectableCategoryChip(
    selected: Boolean,
    label: String,
    onClick: () -> Unit,
) {
    AppFilterChip(
        selected = selected,
        onClick = onClick,
        label = label,
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
    expenseTime: String,
    onPickDate: () -> Unit,
    onPickTime: () -> Unit,
    onUseNow: () -> Unit,
    onClear: () -> Unit,
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
                    Text("消费时间", style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = displayDateTime(expenseTime),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                OutlinedButton(onClick = onPickDate) {
                    Text("选日期")
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onPickTime) {
                    Text("选时间")
                }
                TextButton(onClick = onUseNow) {
                    Text("设为现在")
                }
                TextButton(
                    enabled = expenseTime.isNotBlank(),
                    onClick = onClear,
                ) {
                    Text("清除")
                }
            }
        }
    }
}
