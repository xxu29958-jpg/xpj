package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.AppAsyncImageLayout
import com.ticketbox.ui.components.AppAsyncImagePresentation
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing

// 核对预览随可用宽度裁切；展开原图保留既有 420dp 阅读高度。
private val EvidenceLargeImageHeight = 420.dp

internal data class ExpenseEditEvidenceState(
    val previewImage: ProtectedImage?,
    val fullImage: ProtectedImage?,
    val imageLoading: Boolean,
    val showLargeImage: Boolean,
    val originalTaskAvailable: Boolean = false,
)

internal data class ExpenseEditEvidenceActions(
    val onToggleLargeImage: () -> Unit,
)

/**
 * 证据段：小票截图是本页的核对对象，贴近表单主任务区。只承载证据本身
 * （缩略图 / 看原图 / 重新识别 / 大图展开），不再镜像服务端商家/金额旧值——
 * 表单字段才是当前草稿事实。调用方按持久凭证标志与删除状态决定是否渲染本段。
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
        Box(modifier = Modifier.fillMaxWidth()) {
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
            layout = AppAsyncImageLayout(displayAspectRatio = 2f),
        )
        ExpenseEvidenceActions(
            state = state,
            actions = actions,
            modifier = Modifier.align(Alignment.TopEnd).padding(AppSpacing.smallGap),
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
        if (!state.originalTaskAvailable) AppSecondaryButton(
            modifier = modifier,
            text = when {
                state.imageLoading -> stringResource(R.string.expense_edit_preview_image_button_loading)
                state.showLargeImage -> stringResource(R.string.expense_edit_preview_image_button_collapse)
                else -> stringResource(R.string.expense_edit_preview_image_button_open)
            },
            enabled = !state.imageLoading,
            onClick = actions.onToggleLargeImage,
        )
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
