package com.ticketbox.ui.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.tabularNum

enum class ExpensePreviewMode {
    Compact,
    Comfortable,
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ExpenseCard(
    expense: Expense,
    thumbnail: ProtectedImage? = null,
    previewMode: ExpensePreviewMode = ExpensePreviewMode.Comfortable,
    showActions: Boolean,
    showConfirmAction: Boolean = showActions,
    showRejectAction: Boolean = showActions,
    showDuplicateAction: Boolean = showActions,
    actionsEnabled: Boolean = true,
    onEdit: () -> Unit = {},
    onConfirm: () -> Unit = {},
    onReject: () -> Unit = {},
    onKeepDuplicate: () -> Unit = {},
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    var showRejectDialog by remember(expense.id) { mutableStateOf(false) }
    val isCompact = previewMode == ExpensePreviewMode.Compact
    val cardPadding = if (isCompact) 10.dp else 14.dp
    val contentGap = if (isCompact) 8.dp else 12.dp
    val rowGap = if (isCompact) 10.dp else 12.dp
    val imageSize = if (isCompact) DpSize(width = 82.dp, height = 110.dp) else DpSize(width = 96.dp, height = 128.dp)
    val exchangeMeta = formatExpenseExchangeMeta(expense)

    if (showRejectDialog) {
        AlertDialog(
            onDismissRequest = { if (actionsEnabled) showRejectDialog = false },
            title = { Text("删除这笔待确认账单？") },
            text = { Text("删除后这张截图会标记为已拒绝，不会进入账本。") },
            confirmButton = {
                TextButton(
                    enabled = actionsEnabled,
                    onClick = {
                        showRejectDialog = false
                        onReject()
                    },
                ) {
                    Text("确定删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(
                    enabled = actionsEnabled,
                    onClick = { showRejectDialog = false },
                ) {
                    Text("取消")
                }
            },
        )
    }

    AppGlassCard(
        modifier = Modifier.clickable(enabled = actionsEnabled, onClick = onEdit),
        containerAlpha = 0.96f,
    ) {
        Column(
            modifier = Modifier.padding(cardPadding),
            verticalArrangement = Arrangement.spacedBy(contentGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(rowGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (expense.imagePath != null) {
                    AppAsyncImage(
                        image = thumbnail,
                        placeholder = "截图缩略图加载中",
                        contentScale = ContentScale.Crop,
                        compact = true,
                        compactSize = imageSize,
                    )
                } else {
                    CategoryMark(expense.category)
                }
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(if (isCompact) 4.dp else 6.dp),
                ) {
                    Text(
                        text = expense.merchant?.takeIf { it.isNotBlank() } ?: "待填写商家",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontWeight = AppTextHierarchy.body.weight,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = "${displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt)} · ${
                            if (expense.status == "pending") "截图待确认" else "已入账"
                        }",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = if (expense.amountCents == null) "等待你确认金额" else formatExpensePrimaryAmount(expense, currencyDisplay),
                        style = MaterialTheme.typography.titleLarge.copy(
                            fontSize = AppTypography.amountMedium.size,
                            lineHeight = 28.sp,
                            letterSpacing = 0.sp,
                        ).tabularNum(),
                        color = MaterialTheme.colorScheme.primary,
                        fontWeight = AppTypography.amountMedium.weight,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    exchangeMeta?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        StatusPill(
                            text = expense.category,
                            active = true,
                        )
                        if (expense.amountCents == null) {
                            StatusPill(text = "待补金额", active = false)
                        } else if ((expense.confidence ?: 1.0) < 0.62) {
                            StatusPill(text = "请核对", active = false)
                        }
                        if (expense.duplicateStatus == "suspected") {
                            StatusPill(text = "疑似新账", active = false)
                        }
                    }
                }
            }

            expense.note?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            if (expense.imagePath != null && previewMode == ExpensePreviewMode.Comfortable) {
                val imagePlaceholder = if (expense.thumbnailPath != null) {
                    "截图缩略图加载中"
                } else {
                    "截图已保存，点开后可查看"
                }
                AppAsyncImage(
                    image = thumbnail,
                    placeholder = imagePlaceholder,
                    contentScale = ContentScale.Crop,
                )
            }

            if (expense.duplicateStatus == "suspected") {
                DuplicateNotice(reason = expense.duplicateReason)
            }

            expense.tags?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = "标签：$it",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            if (showActions) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    QuietOutlinedButton(
                        text = "编辑",
                        modifier = Modifier.weight(1f),
                        enabled = actionsEnabled,
                        onClick = onEdit,
                    )
                    if (showConfirmAction) {
                        Button(
                            modifier = Modifier.weight(1f),
                            enabled = actionsEnabled,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = MaterialTheme.colorScheme.primary,
                                contentColor = MaterialTheme.colorScheme.onPrimary,
                            ),
                            onClick = onConfirm,
                        ) {
                            // actionsEnabled=false ⇒ 后台正在 confirm，给一个 scale+check 的反馈：
                            // - 文字 "入账" 淡出
                            // - check 图标从中央 scale 0.6 → 1.0 spring-bounce 进入
                            // 随后整个 row 会被 actionInProgressIds 移除（动画衔接 animateItem）
                            AnimatedContent(
                                targetState = actionsEnabled,
                                transitionSpec = {
                                    (fadeIn(tween(AppMotion.fastMillis)) +
                                        scaleIn(
                                            initialScale = 0.6f,
                                            animationSpec = spring(
                                                dampingRatio = Spring.DampingRatioMediumBouncy,
                                                stiffness = Spring.StiffnessMedium,
                                            ),
                                        )
                                    ) togetherWith (
                                        fadeOut(tween(AppMotion.fastMillis)) +
                                            scaleOut(targetScale = 0.85f, animationSpec = tween(AppMotion.fastMillis))
                                    )
                                },
                                label = "confirmButtonState",
                            ) { ready ->
                                if (ready) {
                                    Text(
                                        text = "入账",
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                } else {
                                    Icon(
                                        imageVector = Icons.Filled.Check,
                                        contentDescription = "已入账",
                                        modifier = Modifier.size(20.dp),
                                    )
                                }
                            }
                        }
                    }
                    if (showRejectAction) {
                        Spacer(Modifier.weight(0.15f))
                        AppOutlinedButton(
                            enabled = actionsEnabled,
                            onClick = { showRejectDialog = true },
                        ) {
                            Text(
                                text = "忽略",
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
                if (showDuplicateAction && expense.duplicateStatus == "suspected") {
                    AppOutlinedButton(
                        enabled = actionsEnabled,
                        onClick = onKeepDuplicate,
                    ) {
                        Text(
                            text = "不是重复，保留",
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun CategoryMark(category: String) {
    Box(
        modifier = Modifier
            .size(54.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.primaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = category.take(1).ifBlank { "账" },
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            textAlign = TextAlign.Center,
        )
    }
}
