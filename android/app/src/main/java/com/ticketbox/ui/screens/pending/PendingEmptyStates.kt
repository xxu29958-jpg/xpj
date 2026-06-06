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
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSecondaryButton

@Composable
internal fun UploadFlowCard() {
    AppContentCard {
        Text(
            text = stringResource(R.string.pending_upload_flow_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FlowStep(
                "1",
                stringResource(R.string.pending_upload_flow_step1_title),
                stringResource(R.string.pending_upload_flow_step1_subtitle),
                modifier = Modifier.weight(1f),
            )
            FlowStep(
                "2",
                stringResource(R.string.pending_upload_flow_step2_title),
                stringResource(R.string.pending_upload_flow_step2_subtitle),
                modifier = Modifier.weight(1f),
            )
            FlowStep(
                "3",
                stringResource(R.string.pending_upload_flow_step3_title),
                stringResource(R.string.pending_upload_flow_step3_subtitle),
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
internal fun UploadProgressCard() {
    AppContentCard {
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
private fun FlowStep(
    number: String,
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = number,
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(1.dp),
        ) {
            Text(title, style = MaterialTheme.typography.labelLarge, fontWeight = AppTextHierarchy.heading.weight)
            Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
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
        verticalArrangement = Arrangement.spacedBy(12.dp),
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
        AppContentCard {
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
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
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
            AppContentCard {
                Column(
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(stringResource(R.string.pending_empty_guide_title), style = MaterialTheme.typography.titleSmall, fontWeight = AppTextHierarchy.heading.weight)
                    Text(stringResource(R.string.pending_empty_guide_step1))
                    Text(stringResource(R.string.pending_empty_guide_step2))
                    Text(stringResource(R.string.pending_empty_guide_step3))
                }
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
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(5.dp),
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
