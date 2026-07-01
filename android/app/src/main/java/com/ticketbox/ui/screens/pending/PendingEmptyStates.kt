package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun UploadProgressCard() {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.pending_upload_progress_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = stringResource(R.string.pending_upload_progress_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
    }
}

@Composable
internal fun EmptyPendingState(
    uploading: Boolean,
    loading: Boolean = false,
    readOnly: Boolean,
    showUploadGuide: Boolean,
    onToggleGuide: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        AppSectionHeader(
            title = if (loading) {
                stringResource(R.string.pending_empty_header_title_loading)
            } else {
                stringResource(R.string.pending_empty_header_title)
            },
            subtitle = if (readOnly) {
                stringResource(R.string.pending_empty_header_subtitle_readonly)
            } else if (loading) {
                stringResource(R.string.pending_empty_header_subtitle_loading)
            } else {
                stringResource(R.string.pending_empty_header_subtitle)
            },
        )
        PendingStateTitle(
            icon = Icons.Filled.AddPhotoAlternate,
            title = if (loading) {
                stringResource(R.string.pending_empty_card_title_loading)
            } else {
                stringResource(R.string.pending_empty_card_title)
            },
            body = if (readOnly) {
                stringResource(R.string.pending_empty_card_body_readonly)
            } else if (loading) {
                stringResource(R.string.pending_empty_card_body_loading)
            } else {
                stringResource(R.string.pending_empty_card_body)
            },
        )
        if (loading) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            if (!readOnly) {
                AppSecondaryButton(
                    text = if (showUploadGuide) {
                        stringResource(R.string.pending_empty_guide_collapse)
                    } else {
                        stringResource(R.string.pending_empty_guide_expand)
                    },
                    modifier = Modifier.weight(1.25f),
                    leadingIcon = Icons.Filled.Info,
                    enabled = !loading,
                    onClick = onToggleGuide,
                )
            }
            AppSecondaryButton(
                text = stringResource(R.string.pending_empty_refresh_button),
                modifier = Modifier.weight(if (readOnly) 1f else 0.75f),
                enabled = !uploading && !loading,
                onClick = onRefresh,
            )
        }
        if (showUploadGuide && !readOnly) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                Text(
                    text = stringResource(R.string.pending_empty_guide_title),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(stringResource(R.string.pending_empty_guide_step1))
                Text(stringResource(R.string.pending_empty_guide_step2))
                Text(stringResource(R.string.pending_empty_guide_step3))
            }
        }
    }
}

@Composable
private fun PendingStateTitle(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    body: String,
) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleSmall,
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
