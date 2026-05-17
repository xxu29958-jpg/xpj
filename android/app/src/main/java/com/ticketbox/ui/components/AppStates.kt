package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppTextHierarchy

/**
 * 统一加载占位组件。
 *
 * - 内部使用 [AppEmptyStateCard]，与空状态共享卡片底版。
 * - 仅做展示职责：不发起任何业务调用，由调用方决定何时显示。
 *
 * v0.10：进度条改为 [SkeletonScaffold] 包裹的骸屏行，按
 * [com.ticketbox.ui.design.LocalSkeletonTokens] 渲染主题色板
 * (midnight 用暖金 alpha，paper / mono 用墨灰)。调用方签名不变；
 * 若调用方未来升级为接管 isLoading 切换，可直接换用 [SkeletonScaffold]。
 */
@Composable
fun AppLoadingState(
    title: String,
    body: String? = null,
    modifier: Modifier = Modifier,
) {
    AppEmptyStateCard(modifier = modifier) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            body?.let {
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            SkeletonScaffold(
                isLoading = true,
                skeleton = {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        SkeletonBlock(modifier = Modifier.fillMaxWidth(fraction = 0.78f).height(10.dp))
                        SkeletonBlock(modifier = Modifier.fillMaxWidth(fraction = 0.55f).height(10.dp))
                    }
                },
                content = {},
            )
        }
    }
}
