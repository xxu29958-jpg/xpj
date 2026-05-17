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
import androidx.compose.material3.MaterialTheme
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
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.components.ExpenseImagePreview
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatAmount

@Composable
internal fun EditDraftPreviewCard(
    expense: Expense,
    previewImage: ProtectedImage?,
    imageLoading: Boolean,
    ocrRunning: Boolean,
    readOnly: Boolean,
    showLargeImage: Boolean,
    onToggleLargeImage: () -> Unit,
    onRetryOcr: () -> Unit,
) {
    AppSolidCard {
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
                        AppOutlinedButton(
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
                        if (!readOnly) {
                            AppOutlinedButton(
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
}

@Composable
internal fun OcrProgressCard() {
    AppLoadingState(
        title = "正在重新识别截图",
        body = "识别结果只会更新草稿，仍需要你核对后确认入账。",
    )
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
    expenseTime: String,
    onPickDate: () -> Unit,
    onPickTime: () -> Unit,
    onUseNow: () -> Unit,
    onClear: () -> Unit,
    enabled: Boolean = true,
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
                    Text("消费时间", style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = displayDateTime(expenseTime),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                AppOutlinedButton(enabled = enabled, onClick = onPickDate) {
                    Text("选日期")
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(enabled = enabled, onClick = onPickTime) {
                    Text("选时间")
                }
                TextButton(enabled = enabled, onClick = onUseNow) {
                    Text("设为现在")
                }
                TextButton(
                    enabled = enabled && expenseTime.isNotBlank(),
                    onClick = onClear,
                ) {
                    Text("清除")
                }
            }
        }
    }
}
