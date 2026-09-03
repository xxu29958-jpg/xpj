package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.AppAsyncImageLayout
import com.ticketbox.ui.components.AppAsyncImagePresentation
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.design.AppSpacing

// 小票缩略图 / 大图尺寸：沿用原 EditDraftPreviewCard 的口径（竖向票据 3:4 缩略、420dp 大图）。
private val EvidenceThumbnailSize = DpSize(width = 104.dp, height = 136.dp)
private val EvidenceLargeImageHeight = 420.dp

internal data class ExpenseEditEvidenceState(
    val previewImage: ProtectedImage?,
    val fullImage: ProtectedImage?,
    val imageLoading: Boolean,
    val ocrRunning: Boolean,
    val readOnly: Boolean,
    val showLargeImage: Boolean,
)

internal data class ExpenseEditEvidenceActions(
    val onToggleLargeImage: () -> Unit,
    val onRetryOcr: () -> Unit,
)

/**
 * 证据段：小票截图是本页的核对对象，贴近表单主任务区。只承载证据本身
 * （缩略图 / 看原图 / 重新识别 / 大图展开），不再镜像服务端商家/金额旧值——
 * 表单字段才是当前草稿事实。调用方保证 imagePath != null 才渲染本段。
 */
@Composable
internal fun ExpenseEditEvidenceSection(
    state: ExpenseEditEvidenceState,
    actions: ExpenseEditEvidenceActions,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.expense_edit_evidence_title),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AppAsyncImage(
                image = state.previewImage,
                presentation = AppAsyncImagePresentation(
                    placeholder = if (state.imageLoading) {
                        stringResource(R.string.expense_edit_preview_image_loading)
                    } else {
                        stringResource(R.string.expense_edit_preview_image_saved)
                    },
                    contentDescription = stringResource(R.string.components_async_image_content_description),
                    contentScale = ContentScale.Crop,
                ),
                layout = AppAsyncImageLayout(compact = true, compactSize = EvidenceThumbnailSize),
            )
            ExpenseEvidenceActions(
                state = state,
                actions = actions,
                modifier = Modifier.weight(1f),
            )
        }
        if (state.showLargeImage) {
            ExpenseEvidenceLargeImage(state)
        }
    }
}

@Composable
private fun ExpenseEvidenceActions(
    state: ExpenseEditEvidenceState,
    actions: ExpenseEditEvidenceActions,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        QuietOutlinedButton(
            text = when {
                state.imageLoading -> stringResource(R.string.expense_edit_preview_image_button_loading)
                state.showLargeImage -> stringResource(R.string.expense_edit_preview_image_button_collapse)
                else -> stringResource(R.string.expense_edit_preview_image_button_open)
            },
            enabled = !state.imageLoading,
            onClick = actions.onToggleLargeImage,
        )
        if (!state.readOnly) {
            QuietOutlinedButton(
                text = if (state.ocrRunning) {
                    stringResource(R.string.expense_edit_preview_recognize_running_button)
                } else {
                    stringResource(R.string.expense_edit_preview_recognize_retry_button)
                },
                enabled = !state.ocrRunning,
                onClick = actions.onRetryOcr,
            )
        }
    }
}

@Composable
private fun ExpenseEvidenceLargeImage(state: ExpenseEditEvidenceState) {
    AppAsyncImage(
        image = state.fullImage ?: state.previewImage,
        presentation = AppAsyncImagePresentation(
            placeholder = if (state.imageLoading) {
                stringResource(R.string.expense_edit_large_image_loading)
            } else {
                stringResource(R.string.expense_edit_large_image_failed)
            },
            contentDescription = stringResource(R.string.components_async_image_content_description),
            contentScale = ContentScale.Fit,
        ),
        layout = AppAsyncImageLayout(displayHeight = EvidenceLargeImageHeight),
    )
}
