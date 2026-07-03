package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Security
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.design.AppAlpha
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
        SettingsSection(
            title = stringResource(R.string.settings_about_section_app_info),
            icon = Icons.Filled.Info,
        ) {
            SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                AboutInfoRow(
                    label = stringResource(R.string.settings_about_label_app),
                    value = stringResource(R.string.settings_about_app_name),
                )
                AboutDivider()
                AboutInfoRow(
                    label = stringResource(R.string.settings_about_label_version),
                    value = stringResource(R.string.settings_about_version, appVersionName, appVersionCode),
                )
            }
        }
        SettingsSection(
            title = stringResource(R.string.settings_about_section_boundaries),
            icon = Icons.Filled.Security,
        ) {
            SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                AboutTrustRow(
                    title = stringResource(R.string.settings_about_confirm_title),
                    body = stringResource(R.string.settings_about_confirm_body),
                )
                AboutDivider()
                AboutTrustRow(
                    title = stringResource(R.string.settings_about_authority_title),
                    body = stringResource(R.string.settings_about_authority_body),
                )
                AboutDivider()
                AboutTrustRow(
                    title = stringResource(R.string.settings_about_privacy_title),
                    body = stringResource(R.string.settings_about_privacy_body),
                )
            }
        }
    }
}

@Composable
private fun AboutInfoRow(
    label: String,
    value: String,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.miniGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            modifier = Modifier.weight(1f),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = AppTextHierarchy.body.weight,
            textAlign = TextAlign.End,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun AboutTrustRow(
    title: String,
    body: String,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.miniGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyMedium,
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
private fun AboutDivider() =
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
