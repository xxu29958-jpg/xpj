package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.SkeletonBlock
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.ExpenseFactUiState

/**
 * A1 凭证段四态：Loading（骨架）/ Failed（错误 + 重试）/ Cleaned / Empty 与
 * 有图（缩略→大图）。加载失败绝不冒充「没有凭证图片」。
 */
@Composable
internal fun FactMediaSection(
    state: ExpenseFactUiState,
    onLoadFullImage: () -> Unit,
    onRetryThumbnail: () -> Unit,
) {
    val expense = state.expense ?: return
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        when {
            state.fullImage != null || state.thumbnail != null -> {
                FactReceiptImageBranch(state = state, onLoadFullImage = onLoadFullImage)
            }
            state.thumbnailLoadState == ExpenseDetailDataLoadState.Loading -> {
                Text(
                    text = stringResource(R.string.expense_fact_media_loading),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                SkeletonBlock(modifier = Modifier.fillMaxWidth().height(AppSpacing.sectionGap * 2))
            }
            state.thumbnailLoadState == ExpenseDetailDataLoadState.Failed -> {
                Text(
                    text = state.thumbnailMessage?.asString()
                        ?: stringResource(R.string.expense_fact_media_failed),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                TextButton(onClick = onRetryThumbnail) {
                    Text(text = stringResource(R.string.expense_fact_retry))
                }
            }
            expense.imageDeletedAt != null -> {
                Text(
                    text = stringResource(R.string.expense_fact_image_cleaned),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            else -> {
                Text(
                    text = stringResource(R.string.expense_fact_image_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun FactReceiptImageBranch(
    state: ExpenseFactUiState,
    onLoadFullImage: () -> Unit,
) {
    AppAsyncImage(
        image = state.fullImage ?: state.thumbnail,
        modifier = Modifier.fillMaxWidth(),
    )
    if (state.fullImage == null) {
        QuietOutlinedButton(
            text = if (state.imageLoading) {
                stringResource(R.string.expense_edit_large_image_loading)
            } else {
                stringResource(R.string.expense_fact_image_view_full)
            },
            onClick = onLoadFullImage,
            enabled = !state.imageLoading,
        )
    }
}
