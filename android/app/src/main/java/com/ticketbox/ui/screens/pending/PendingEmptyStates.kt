package com.ticketbox.ui.screens.pending

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import com.ticketbox.R
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppWindowWidthClass
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.mascot.MascotEmptyIllustration

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
    state: EmptyPendingStateModel,
    onUploadScreenshot: () -> Unit,
    onToggleGuide: () -> Unit,
    onRefresh: () -> Unit,
) {
    // 单一主任务焦点构图：中宽以上窗口内容居中并封顶焦点宽度，
    // 主操作不再横跨整窗；compact 单栏维持全宽。
    val focusCap = if (LocalAppAdaptiveLayoutPolicy.current.widthClass == AppWindowWidthClass.Compact) {
        null
    } else {
        AppAdaptiveBreakpoints.focusContentMaxWidth
    }
    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = Alignment.TopCenter,
    ) {
        Surface(
            modifier = if (focusCap != null) {
                Modifier.widthIn(max = focusCap).fillMaxWidth()
            } else {
                Modifier.fillMaxWidth()
            },
            shape = RoundedCornerShape(AppRadius.large),
            color = LocalThemeVisuals.current.solidCard,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(AppSpacing.cardPadding),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                if (!state.loading) {
                    // 插画视觉内容（票据+投影）一直画到画布底边，这里为标题补一档
                    // 真实语义间距，避免装饰性 Canvas 的视觉边缘贴上文字。
                    MascotEmptyIllustration(
                        modifier = Modifier.padding(bottom = AppSpacing.contentGap),
                    )
                }
                PendingStateTitle(
                    title = if (state.loading) {
                        stringResource(R.string.pending_empty_card_title_loading)
                    } else {
                        stringResource(R.string.pending_empty_card_title)
                    },
                    body = if (state.readOnly) {
                        stringResource(R.string.pending_empty_card_body_readonly)
                    } else if (state.loading) {
                        stringResource(R.string.pending_empty_card_body_loading)
                    } else {
                        stringResource(R.string.pending_empty_card_body)
                    },
                )
                if (state.loading) {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
                emptyPendingUploadCta(
                    uploading = state.uploading,
                    loading = state.loading,
                    readOnly = state.readOnly,
                )?.let { cta ->
                    AppPrimaryButton(
                        text = stringResource(cta.labelRes),
                        icon = Icons.Filled.AddPhotoAlternate,
                        modifier = Modifier.fillMaxWidth(),
                        enabled = cta.enabled,
                        onClick = onUploadScreenshot,
                    )
                }
                PendingEmptyActions(
                    state = state,
                    onToggleGuide = onToggleGuide,
                    onRefresh = onRefresh,
                )
                if (state.showUploadGuide && !state.readOnly) {
                    PendingUploadGuide()
                }
            }
        }
    }
}

internal data class EmptyPendingStateModel(
    val uploading: Boolean,
    val loading: Boolean = false,
    val readOnly: Boolean,
    val showUploadGuide: Boolean,
)

/**
 * 空态主上传 CTA 的纯模型：只读角色没有上传入口（返回 null）；上传中 / 加载中
 * 置灰防重入。标签复用页头 CTA 文案，不新增字符串。
 */
internal data class EmptyPendingUploadCta(
    @param:StringRes val labelRes: Int,
    val enabled: Boolean,
)

internal fun emptyPendingUploadCta(
    uploading: Boolean,
    loading: Boolean,
    readOnly: Boolean,
): EmptyPendingUploadCta? {
    if (readOnly) return null
    return EmptyPendingUploadCta(
        labelRes = if (uploading) {
            R.string.pending_top_cta_uploading
        } else {
            R.string.pending_top_cta_upload
        },
        enabled = !uploading && !loading,
    )
}

@Composable
private fun PendingUploadGuide() {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.pending_empty_guide_title),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        PendingGuideStep(text = stringResource(R.string.pending_empty_guide_step1))
        PendingGuideStep(text = stringResource(R.string.pending_empty_guide_step2))
        PendingGuideStep(text = stringResource(R.string.pending_empty_guide_step3))
    }
}

@Composable
private fun PendingEmptyActions(
    state: EmptyPendingStateModel,
    onToggleGuide: () -> Unit,
    onRefresh: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (!state.readOnly) {
            PendingInlineAction(
                text = if (state.showUploadGuide) {
                    stringResource(R.string.pending_empty_guide_collapse)
                } else {
                    stringResource(R.string.pending_empty_guide_expand)
                },
                icon = Icons.Filled.Info,
                enabled = !state.loading,
                onClick = onToggleGuide,
            )
        }
        PendingInlineAction(
            text = stringResource(R.string.pending_empty_refresh_button),
            icon = Icons.Filled.Refresh,
            enabled = !state.uploading && !state.loading,
            onClick = onRefresh,
        )
    }
}

@Composable
private fun PendingInlineAction(
    text: String,
    icon: ImageVector,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    TextButton(
        enabled = enabled,
        onClick = onClick,
        contentPadding = PaddingValues(
            horizontal = AppSpacing.smallGap,
            vertical = AppSpacing.tinyGap,
        ),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
        )
        Spacer(modifier = Modifier.width(AppSpacing.tinyGap))
        Text(
            text = text,
            fontWeight = AppTextHierarchy.heading.weight,
        )
    }
}

@Composable
private fun PendingGuideStep(text: String) {
    Text(
        text = text,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun PendingStateTitle(
    title: String,
    body: String,
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            textAlign = TextAlign.Center,
        )
        Text(
            text = body,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
    }
}
