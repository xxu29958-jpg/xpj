package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme

@Preview(showBackground = true)
@Composable
private fun AppVisualComponentsPreview() {
    TicketboxTheme(skin = AppSkin.Paper) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            AppSectionHeader(
                title = "待确认账单",
                subtitle = "截图上传后不会自动入账",
            )
            AppHeroCard {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = "等待你确认",
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.78f),
                    )
                    Text(
                        text = "0 张",
                        color = MaterialTheme.colorScheme.onPrimary,
                        style = MaterialTheme.typography.headlineLarge,
                        fontWeight = FontWeight.Black,
                    )
                }
            }
            AppGlassCard {
                Row(
                    modifier = Modifier.padding(20.dp),
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    ReceiptIllustration(compact = true)
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        AppStatusPill(text = "无待确认")
                        Text("识别结果只是草稿")
                    }
                }
            }
            AppEmptyStateCard {
                Row(
                    modifier = Modifier.padding(20.dp),
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    ReceiptIllustration(compact = true)
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            text = "还没有待确认账单",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Black,
                        )
                        Text(
                            text = "截图上传后不会自动入账，你确认后才会记录。",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            AppSolidCard {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    AppFilterChip(label = "餐饮", selected = true, onClick = {})
                    AppPrimaryButton(
                        text = "上传截图",
                        icon = Icons.Filled.AddPhotoAlternate,
                        modifier = Modifier.fillMaxWidth(),
                        onClick = {},
                    )
                    AppSecondaryButton(
                        text = "刷新",
                        modifier = Modifier.fillMaxWidth(),
                        onClick = {},
                    )
                }
            }
            SettingsEntryCard(
                title = "外观与主题",
                subtitle = "主题皮肤、自定义背景、沉浸强度",
                icon = Icons.Filled.Palette,
                onClick = {},
            )
            AppBottomNav(
                items = listOf(
                    AppBottomNavItem("pending", "待确认", Icons.Filled.CheckCircle),
                    AppBottomNavItem("ledger", "账本", Icons.AutoMirrored.Filled.ReceiptLong),
                    AppBottomNavItem("stats", "统计", Icons.Filled.BarChart),
                    AppBottomNavItem("settings", "设置", Icons.Filled.Settings),
                ),
                selectedKey = "pending",
                onSelect = {},
            )
        }
    }
}
