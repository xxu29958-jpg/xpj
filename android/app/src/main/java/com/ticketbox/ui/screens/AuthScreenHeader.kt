package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.ui.design.AppTypography

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
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            text = stringResource(R.string.auth_header_app_label),
            style = MaterialTheme.typography.titleMedium.copy(
                fontSize = AppTypography.appLabel.size,
                lineHeight = 20.sp,
                letterSpacing = 0.06.sp,
            ),
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = AppTypography.appLabel.weight,
        )
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge.copy(
                fontSize = AppTypography.pageTitle.size,
                lineHeight = 34.sp,
                letterSpacing = 0.sp,
            ),
            fontWeight = AppTypography.pageTitle.weight,
        )
        Text(
            text = subtitle,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
