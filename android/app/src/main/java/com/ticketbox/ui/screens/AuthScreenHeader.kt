package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing

/**
 * Auth 页（绑定 / 解锁）共享的居中标题骨架。
 *
 * 与主页面 `ScreenHeader` 共享同一套 typography token（eyebrow + pageTitle + body），
 * 让首次启动与登录页和已绑定后的页面在字号层级上保持一致。
 */
@Composable
internal fun AuthScreenHeader(
    title: String,
    subtitle: String,
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.auth_header_app_label),
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            text = title,
            style = MaterialTheme.typography.displaySmall,
        )
        Text(
            text = subtitle,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
