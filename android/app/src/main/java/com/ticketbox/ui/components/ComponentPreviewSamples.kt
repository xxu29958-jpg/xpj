package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.EventNote
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.People
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.AppTextHierarchy
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
            AppContentCard {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = "等待你确认",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = "0 张",
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.headlineLarge,
                        fontWeight = AppTextHierarchy.heading.weight,
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
                        StatusPill(text = "无待确认", active = true)
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
                            fontWeight = AppTextHierarchy.heading.weight,
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
                // 对齐生产五域主底栏：所有标签常显，账户与设置不占任务域位置。
                items = listOf(
                    AppPrimaryNavItem("inbox", stringResource(R.string.nav_domain_inbox), Icons.Filled.Inbox),
                    AppPrimaryNavItem(
                        "transactions",
                        stringResource(R.string.nav_domain_transactions),
                        Icons.AutoMirrored.Filled.ReceiptLong,
                    ),
                    AppPrimaryNavItem("obligations", stringResource(R.string.nav_domain_obligations), Icons.Filled.People),
                    AppPrimaryNavItem("plans", stringResource(R.string.nav_domain_plans), Icons.AutoMirrored.Filled.EventNote),
                    AppPrimaryNavItem("insights", stringResource(R.string.nav_domain_insights), Icons.Filled.Insights),
                ),
                selectedKey = "inbox",
                onSelect = {},
            )
        }
    }
}
