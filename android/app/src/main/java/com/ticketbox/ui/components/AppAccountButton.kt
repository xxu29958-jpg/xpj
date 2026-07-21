package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing

/**
 * 一级页面共用的账户入口。它属于全局产品导航，不是某个业务域自己的工具按钮。
 */
@Composable
fun AppAccountButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    IconButton(
        onClick = onClick,
        modifier = modifier
            .size(AppSpacing.controlMinHeight),
    ) {
        Box(
            modifier = Modifier
                .size(AppAccountButtonTokens.AvatarSize)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.72f))
                .border(
                    width = AppAccountButtonTokens.BorderWidth,
                    color = MaterialTheme.colorScheme.outlineVariant,
                    shape = CircleShape,
                ),
            contentAlignment = androidx.compose.ui.Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.Filled.Person,
                contentDescription = stringResource(R.string.navigation_open_account),
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(AppAccountButtonTokens.IconSize),
            )
        }
    }
}

private object AppAccountButtonTokens {
    val AvatarSize: Dp = 34.dp
    val BorderWidth: Dp = 1.dp
    val IconSize: Dp = 18.dp
}
