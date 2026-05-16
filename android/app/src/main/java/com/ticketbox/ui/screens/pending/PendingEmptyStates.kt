package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSecondaryButton

@Composable
internal fun UploadFlowCard() {
    AppContentCard {
        Text(
            text = "上传后怎么处理",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Black,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FlowStep("1", "上传", "选截图", modifier = Modifier.weight(1f))
            FlowStep("2", "核对", "补金额", modifier = Modifier.weight(1f))
            FlowStep("3", "入账", "确认后记录", modifier = Modifier.weight(1f))
        }
    }
}

@Composable
internal fun UploadProgressCard() {
    AppContentCard {
        Text(
            text = "正在创建待确认账单",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Black,
        )
        Text(
            text = "上传完成后会自动刷新。新截图仍然只是草稿，不会直接入账。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun FlowStep(
    number: String,
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = number,
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Black,
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(1.dp),
        ) {
            Text(title, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Black)
            Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
internal fun EmptyPendingState(
    uploading: Boolean,
    loading: Boolean = false,
    readOnly: Boolean,
    showUploadGuide: Boolean,
    onToggleGuide: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        AppSectionHeader(
            title = if (loading) "正在整理待确认" else "待处理",
            subtitle = if (readOnly) {
                "当前角色可查看待确认账单，不能新增或修改"
            } else if (loading) {
                "同步完成后，这里会立刻显示需要核对的账单"
            } else {
                "上传截图后，会出现在这里等你确认"
            },
        )
        AppContentCard {
            PendingStateTitle(
                icon = Icons.Filled.AddPhotoAlternate,
                title = if (loading) "正在整理待确认账单" else "还没有待确认账单",
                body = if (readOnly) {
                    "当前账本没有需要查看的待确认账单。"
                } else if (loading) {
                    "截图上传后会先进入待确认区，确认后才会入账。"
                } else {
                    "截图上传后会先进入待确认区。核对清楚后，再把它记到账本里。"
                },
            )
            if (loading) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (!readOnly) {
                AppSecondaryButton(
                    text = if (showUploadGuide) "收起 iPhone 方法" else "iPhone 快捷指令",
                    modifier = Modifier.weight(1.25f),
                    leadingIcon = Icons.Filled.Info,
                    enabled = !loading,
                    onClick = onToggleGuide,
                )
            }
            AppSecondaryButton(
                text = "刷新",
                modifier = Modifier.weight(if (readOnly) 1f else 0.75f),
                enabled = !uploading && !loading,
                onClick = onRefresh,
            )
        }
        if (showUploadGuide && !readOnly) {
            AppContentCard {
                Column(
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("iPhone 上传方法", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Black)
                    Text("1. 打开账单截图，点分享。")
                    Text("2. 选择\u201C上传到小票夹\u201D快捷指令。")
                    Text("3. 上传成功后回到这里刷新。")
                }
            }
        }
    }
}

@Composable
private fun PendingStateTitle(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    body: String,
) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Black,
            )
            Text(
                text = body,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
