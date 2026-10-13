package com.ticketbox.ui.components

import androidx.compose.ui.res.vectorResource
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import com.ticketbox.R
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

enum class DataAuthorityTone {
    Backend,
    Refreshing,
    LocalCache,
    ReadOnly,
}

/** Callers must have a result before using Backend; neither Backend nor Refreshing implies offline storage. */
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
        DataAuthorityTone.Backend -> MaterialTheme.colorScheme.onSurfaceVariant
        DataAuthorityTone.Refreshing -> MaterialTheme.colorScheme.secondary
        DataAuthorityTone.LocalCache -> MaterialTheme.colorScheme.tertiary
        DataAuthorityTone.ReadOnly -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val icon = when (tone) {
        DataAuthorityTone.Backend -> null
        DataAuthorityTone.Refreshing -> ImageVector.vectorResource(R.drawable.ic_lucide_refresh_cw)
        DataAuthorityTone.LocalCache,
        DataAuthorityTone.ReadOnly,
        -> ImageVector.vectorResource(R.drawable.ic_lucide_info)
    }
    DataAuthorityStripContent(
        title = title,
        body = body,
        icon = icon,
        titleStyle = SpanStyle(
            color = accent,
            fontWeight = if (tone == DataAuthorityTone.Backend) FontWeight.Normal else AppTextHierarchy.body.weight,
        ),
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
    icon: ImageVector?,
    titleStyle: SpanStyle,
    modifier: Modifier = Modifier,
) {
    val separator = stringResource(R.string.components_data_authority_separator)
    val line = buildAnnotatedString {
        withStyle(titleStyle) {
            append(title)
        }
        append(separator)
        append(body)
    }
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = AppSpacing.miniGap, vertical = AppSpacing.tinyGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.Top,
    ) {
        if (icon != null) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.size(AppSpacing.compactGap),
                tint = titleStyle.color.copy(alpha = AppAlpha.heavy),
            )
        }
        Text(
            text = line,
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
