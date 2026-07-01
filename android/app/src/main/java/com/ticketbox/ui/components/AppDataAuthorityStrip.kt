package com.ticketbox.ui.components

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

enum class DataAuthorityTone {
    Backend,
    Refreshing,
    LocalCache,
    ReadOnly,
}

@Composable
fun AppDataAuthorityStrip(
    tone: DataAuthorityTone,
    modifier: Modifier = Modifier,
    @StringRes localCacheBodyRes: Int = R.string.components_data_authority_cache_body,
) {
    AppDataAuthorityStrip(
        title = stringResource(dataAuthorityTitleRes(tone)),
        body = stringResource(dataAuthorityBodyRes(tone, localCacheBodyRes)),
        tone = tone,
        modifier = modifier,
    )
}

@Composable
fun AppDataAuthorityStrip(
    title: String,
    body: String,
    tone: DataAuthorityTone,
    modifier: Modifier = Modifier,
) {
    val accent = when (tone) {
        DataAuthorityTone.Backend -> MaterialTheme.colorScheme.primary
        DataAuthorityTone.Refreshing -> MaterialTheme.colorScheme.secondary
        DataAuthorityTone.LocalCache -> MaterialTheme.colorScheme.tertiary
        DataAuthorityTone.ReadOnly -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val icon = when (tone) {
        DataAuthorityTone.Backend -> Icons.Filled.CloudDone
        DataAuthorityTone.Refreshing -> Icons.Filled.Sync
        DataAuthorityTone.LocalCache,
        DataAuthorityTone.ReadOnly,
        -> Icons.Filled.Info
    }
    DataAuthorityStripContent(
        title = title,
        body = body,
        icon = icon,
        accent = accent,
        modifier = modifier,
    )
}

@StringRes
private fun dataAuthorityTitleRes(tone: DataAuthorityTone): Int = when (tone) {
    DataAuthorityTone.Backend -> R.string.components_data_authority_backend_title
    DataAuthorityTone.Refreshing -> R.string.components_data_authority_refreshing_title
    DataAuthorityTone.LocalCache -> R.string.components_data_authority_cache_title
    DataAuthorityTone.ReadOnly -> R.string.components_data_authority_readonly_title
}

@StringRes
private fun dataAuthorityBodyRes(
    tone: DataAuthorityTone,
    @StringRes localCacheBodyRes: Int,
): Int = when (tone) {
    DataAuthorityTone.Backend -> R.string.components_data_authority_backend_body
    DataAuthorityTone.Refreshing -> R.string.components_data_authority_refreshing_body
    DataAuthorityTone.LocalCache -> localCacheBodyRes
    DataAuthorityTone.ReadOnly -> R.string.components_data_authority_readonly_body
}

@Composable
private fun DataAuthorityStripContent(
    title: String,
    body: String,
    icon: ImageVector,
    accent: Color,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(
                color = accent.copy(alpha = AppAlpha.subtle),
                shape = RoundedCornerShape(AppRadius.extraSmall),
            )
            .border(
                width = AppSpacing.tinyGap / 2f,
                color = accent.copy(alpha = AppAlpha.medium),
                shape = RoundedCornerShape(AppRadius.extraSmall),
            )
            .padding(horizontal = AppSpacing.contentGap, vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            modifier = Modifier.size(AppSpacing.cardPadding),
            tint = accent,
        )
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(
                text = title,
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = body,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
