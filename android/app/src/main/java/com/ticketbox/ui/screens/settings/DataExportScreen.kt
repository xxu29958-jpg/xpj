package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.SettingsUiState

internal enum class DataExportScopeKind {
    Authority,
    OfflineCopy,
    ExportScope,
}

internal data class DataExportScopeRowModel(
    val kind: DataExportScopeKind,
    @param:StringRes val titleRes: Int,
    @param:StringRes val bodyRes: Int,
)

internal fun dataExportScopeRows(): List<DataExportScopeRowModel> = listOf(
    DataExportScopeRowModel(
        kind = DataExportScopeKind.Authority,
        titleRes = R.string.settings_data_export_authority_label,
        bodyRes = R.string.settings_data_export_authority_body,
    ),
    DataExportScopeRowModel(
        kind = DataExportScopeKind.OfflineCopy,
        titleRes = R.string.settings_data_export_cache_label,
        bodyRes = R.string.settings_data_export_cache_body,
    ),
    DataExportScopeRowModel(
        kind = DataExportScopeKind.ExportScope,
        titleRes = R.string.settings_data_export_export_label,
        bodyRes = R.string.settings_data_export_export_body,
    ),
)

@Composable
fun DataExportScreen(
    state: SettingsUiState,
    onBack: () -> Unit,
    onSync: () -> Unit,
    onClearCache: () -> Unit,
) {
    var showClearCacheDialog by remember { mutableStateOf(false) }

    if (showClearCacheDialog) {
        AlertDialog(
            onDismissRequest = { showClearCacheDialog = false },
            title = { Text(stringResource(R.string.settings_data_export_clear_dialog_title)) },
            text = { Text(stringResource(R.string.settings_data_export_clear_dialog_text)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearCacheDialog = false
                        onClearCache()
                    },
                ) {
                    Text(
                        text = stringResource(R.string.settings_data_export_clear_dialog_confirm),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = { showClearCacheDialog = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.settings_data_export_page_title),
        subtitle = stringResource(R.string.settings_data_export_page_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        SettingsSection(
            title = stringResource(R.string.settings_data_export_section_refresh_cache),
            icon = Icons.Filled.FileDownload,
        ) {
            DataExportScopeSection()
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
            DataExportActions(
                busy = state.busy,
                onSync = onSync,
                onClearCacheClick = { showClearCacheDialog = true },
            )
        }
    }
}

@Composable
private fun DataExportScopeSection() {
    val rows = remember { dataExportScopeRows() }
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
        rows.forEachIndexed { index, row ->
            if (index > 0) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
            }
            DataExportScopeRow(row)
        }
    }
}

@Composable
private fun DataExportScopeRow(row: DataExportScopeRowModel) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.Top,
    ) {
        DataExportIconBox(icon = row.kind.icon())
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(row.titleRes),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(row.bodyRes),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun DataExportIconBox(icon: ImageVector) {
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

@Composable
private fun DataExportActions(
    busy: Boolean,
    onSync: () -> Unit,
    onClearCacheClick: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            AppPrimaryButton(
                text = stringResource(
                    if (busy) {
                        R.string.settings_data_export_button_refreshing
                    } else {
                        R.string.settings_data_export_button_refresh
                    },
                ),
                icon = Icons.Filled.RestartAlt,
                modifier = Modifier.weight(1f),
                enabled = !busy,
                onClick = onSync,
            )
            DataExportClearCacheButton(
                modifier = Modifier.weight(1f),
                onClick = onClearCacheClick,
            )
        }
        Text(
            text = stringResource(R.string.settings_data_export_action_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun DataExportClearCacheButton(
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    AppOutlinedButton(
        modifier = modifier,
        danger = true,
        onClick = onClick,
    ) {
        Icon(
            imageVector = Icons.Filled.DeleteOutline,
            contentDescription = null,
            modifier = Modifier.size(18.dp),
        )
        Box(modifier = Modifier.width(AppSpacing.smallGap))
        Text(
            text = stringResource(R.string.settings_data_export_button_clear_cache),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            softWrap = false,
        )
    }
}

private fun DataExportScopeKind.icon(): ImageVector = when (this) {
    DataExportScopeKind.Authority -> Icons.Filled.CloudDone
    DataExportScopeKind.OfflineCopy -> Icons.Filled.Devices
    DataExportScopeKind.ExportScope -> Icons.Filled.FileDownload
}
