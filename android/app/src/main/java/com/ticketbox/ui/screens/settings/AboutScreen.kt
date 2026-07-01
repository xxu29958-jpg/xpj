package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Security
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
fun AboutScreen(
    appVersionName: String,
    appVersionCode: Int,
    onBack: () -> Unit,
) {
    SettingsPageFrame(
        title = stringResource(R.string.settings_about_page_title),
        subtitle = stringResource(R.string.settings_about_page_subtitle),
        onBack = onBack,
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            AboutProductHeader(
                appVersionName = appVersionName,
                appVersionCode = appVersionCode,
            )
            HorizontalDivider(
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
            )
            AboutTrustRow(
                icon = Icons.Filled.Check,
                title = stringResource(R.string.settings_about_confirm_title),
                body = stringResource(R.string.settings_about_confirm_body),
            )
            AboutTrustRow(
                icon = Icons.Filled.CloudDone,
                title = stringResource(R.string.settings_about_authority_title),
                body = stringResource(R.string.settings_about_authority_body),
            )
            AboutTrustRow(
                icon = Icons.Filled.Security,
                title = stringResource(R.string.settings_about_privacy_title),
                body = stringResource(R.string.settings_about_privacy_body),
            )
        }
    }
}

@Composable
private fun AboutProductHeader(
    appVersionName: String,
    appVersionCode: Int,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        AboutIconBox(icon = Icons.Filled.Info)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(R.string.settings_about_app_name),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.settings_about_version, appVersionName, appVersionCode),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AboutTrustRow(
    icon: ImageVector,
    title: String,
    body: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.Top,
    ) {
        AboutIconBox(icon = icon)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = body,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AboutIconBox(icon: ImageVector) {
    Box(
        modifier = Modifier
            .size(AppSpacing.controlMinHeight)
            .clip(RoundedCornerShape(AppRadius.small))
            .background(MaterialTheme.colorScheme.primary.copy(alpha = AppAlpha.subtle)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
    }
}
