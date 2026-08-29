package com.ticketbox.ui.screens.pending

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoFixHigh
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.viewmodel.PendingEnrichmentFeedbackKind
import com.ticketbox.viewmodel.PendingEnrichmentUiState

/**
 * 收件队列头的识别状态带（ambient status band）：上传后的 OCR/后台识别在
 * Pending 内唯一的环境化表达。单条、队列头、非第二队列；不做逐行 chip、
 * 不展示假百分比。视觉语言与 [com.ticketbox.ui.components.AppStatusBanner]
 * 同源（三端共享的 state bg/fg/border token），另带图标与最多一个动作。
 *
 * 呈现决策拆为声明式 [FEEDBACK_KIND_SPECS] 表 + 聚焦小函数
 * （[pendingEnrichmentActiveModel] / [pendingEnrichmentActiveDetail] /
 * [pendingEnrichmentFeedbackAction]），纯逻辑可单测；组合层只渲染。
 * 文案与「重试检查≠重新 OCR」的措辞边界是冻结合同，改动需先过产品裁决。
 */

internal enum class PendingEnrichmentBandTone {
    Info,
    Success,
    Warn,
    Danger,
    Neutral,
}

internal enum class PendingEnrichmentBandAction {
    /** 打开反馈对应账单（立即核对/去补全/查看账单/打开账单共用同一导航）。 */
    OpenExpense,

    /** 仅重试状态观察（PendingViewModel.retryEnrichmentObservation），不是重新 OCR。 */
    RetryObservation,
}

internal data class PendingEnrichmentBandModel(
    val tone: PendingEnrichmentBandTone,
    @param:StringRes val titleRes: Int,
    /** 仅「正在识别 %1$d 张」类计数文案使用；null = 该文案无占位参数。 */
    val titleArg: Int? = null,
    @param:StringRes val detailRes: Int? = null,
    val detailArg: Int? = null,
    @param:StringRes val actionLabelRes: Int? = null,
    val action: PendingEnrichmentBandAction? = null,
    /** null = 仅活动计数（无终态反馈）。图标选择在组合层按 kind 决定。 */
    val kind: PendingEnrichmentFeedbackKind? = null,
)

/** 每个终态 kind 的静态呈现规格：tone、主文案、以及「打开账单」类动作的标签。 */
private data class PendingEnrichmentKindSpec(
    val tone: PendingEnrichmentBandTone,
    @param:StringRes val titleRes: Int,
    /** 非 null 表示该 kind 允许 OpenExpense 动作（仍需目标账单在队列内）。 */
    @param:StringRes val openExpenseLabelRes: Int?,
)

private val FEEDBACK_KIND_SPECS: Map<PendingEnrichmentFeedbackKind, PendingEnrichmentKindSpec> = mapOf(
    PendingEnrichmentFeedbackKind.Updated to PendingEnrichmentKindSpec(
        tone = PendingEnrichmentBandTone.Success,
        titleRes = R.string.pending_enrichment_updated,
        openExpenseLabelRes = R.string.pending_enrichment_action_review,
    ),
    PendingEnrichmentFeedbackKind.NoResult to PendingEnrichmentKindSpec(
        tone = PendingEnrichmentBandTone.Warn,
        titleRes = R.string.pending_enrichment_no_result,
        openExpenseLabelRes = R.string.pending_enrichment_action_complete,
    ),
    PendingEnrichmentFeedbackKind.Conflict to PendingEnrichmentKindSpec(
        tone = PendingEnrichmentBandTone.Info,
        titleRes = R.string.pending_enrichment_conflict,
        openExpenseLabelRes = R.string.pending_enrichment_action_view,
    ),
    PendingEnrichmentFeedbackKind.Failed to PendingEnrichmentKindSpec(
        tone = PendingEnrichmentBandTone.Danger,
        titleRes = R.string.pending_enrichment_failed,
        openExpenseLabelRes = R.string.pending_enrichment_action_open,
    ),
    PendingEnrichmentFeedbackKind.Cancelled to PendingEnrichmentKindSpec(
        tone = PendingEnrichmentBandTone.Neutral,
        titleRes = R.string.pending_enrichment_cancelled,
        openExpenseLabelRes = null,
    ),
    PendingEnrichmentFeedbackKind.NotPending to PendingEnrichmentKindSpec(
        tone = PendingEnrichmentBandTone.Neutral,
        titleRes = R.string.pending_enrichment_not_pending,
        openExpenseLabelRes = null,
    ),
    PendingEnrichmentFeedbackKind.Unavailable to PendingEnrichmentKindSpec(
        tone = PendingEnrichmentBandTone.Warn,
        titleRes = R.string.pending_enrichment_unavailable,
        openExpenseLabelRes = null,
    ),
)

/**
 * 状态带呈现决策：
 * - 无活动任务且无终态反馈 → null（带不出现）；
 * - 只有活动任务 → 计数文案 + 「完成后列表会自动更新」；
 * - 有终态反馈 → 反馈为主文案；若仍有任务在跑，副行报「还有 N 张正在识别」，
 *   终态不得吃掉活动计数；
 * - Updated/NoResult/Conflict/Failed 仅当目标账单仍在当前队列（[feedbackTargetPresent]）
 *   时给 OpenExpense 动作；Unavailable 恒给 RetryObservation。
 */
internal fun pendingEnrichmentBandModel(
    state: PendingEnrichmentUiState,
    feedbackTargetPresent: Boolean,
): PendingEnrichmentBandModel? {
    val feedback = state.feedback
        ?: return pendingEnrichmentActiveModel(state.activeCount)
    val spec = FEEDBACK_KIND_SPECS.getValue(feedback.kind)
    val (action, actionLabelRes) = pendingEnrichmentFeedbackAction(spec, feedback.kind, feedbackTargetPresent)
    val (detailRes, detailArg) = pendingEnrichmentActiveDetail(state.activeCount)
    return PendingEnrichmentBandModel(
        tone = spec.tone,
        titleRes = spec.titleRes,
        detailRes = detailRes,
        detailArg = detailArg,
        actionLabelRes = actionLabelRes,
        action = action,
        kind = feedback.kind,
    )
}

/** 仅活动计数（无终态反馈）时的模型；count ≤ 0 即无带。 */
private fun pendingEnrichmentActiveModel(activeCount: Int): PendingEnrichmentBandModel? {
    if (activeCount <= 0) return null
    return PendingEnrichmentBandModel(
        tone = PendingEnrichmentBandTone.Info,
        titleRes = R.string.pending_enrichment_active,
        titleArg = activeCount,
        detailRes = R.string.pending_enrichment_active_hint,
    )
}

/** 终态反馈在场时的副行：仍有任务在跑则报数，不让终态吃掉活动计数。 */
private fun pendingEnrichmentActiveDetail(activeCount: Int): Pair<Int?, Int?> =
    if (activeCount > 0) {
        R.string.pending_enrichment_active_more to activeCount
    } else {
        null to null
    }

/** 终态反馈的动作边界：Unavailable 恒可重试检查；可导航 kind 需目标仍在队列。 */
private fun pendingEnrichmentFeedbackAction(
    spec: PendingEnrichmentKindSpec,
    kind: PendingEnrichmentFeedbackKind,
    feedbackTargetPresent: Boolean,
): Pair<PendingEnrichmentBandAction?, Int?> = when {
    kind == PendingEnrichmentFeedbackKind.Unavailable ->
        PendingEnrichmentBandAction.RetryObservation to R.string.pending_enrichment_action_retry_check
    spec.openExpenseLabelRes != null && feedbackTargetPresent ->
        PendingEnrichmentBandAction.OpenExpense to spec.openExpenseLabelRes
    else -> null to null
}

@Composable
internal fun PendingEnrichmentStatusBand(
    state: PendingEnrichmentUiState,
    feedbackTargetPresent: Boolean,
    onOpenFeedbackExpense: () -> Unit,
    onRetryObservation: () -> Unit,
) {
    val model = pendingEnrichmentBandModel(state, feedbackTargetPresent) ?: return
    val palette = LocalStateTokens.current.forBandTone(model.tone)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.small))
            .background(palette.bg)
            .border(1.dp, palette.border, RoundedCornerShape(AppRadius.small))
            .padding(horizontal = AppSpacing.cardGap, vertical = AppSpacing.compactGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = bandIcon(model.kind),
            contentDescription = null,
            tint = palette.fg,
            modifier = Modifier.size(AppIconSize.compact),
        )
        // 文案区合并为一个 Polite liveRegion 节点，状态变化整体播报；
        // 动作按钮自带点击语义，不参与合并，仍可独立聚焦。
        Column(
            modifier = Modifier
                .weight(1f)
                .semantics(mergeDescendants = true) {
                    liveRegion = LiveRegionMode.Polite
                },
        ) {
            Text(
                text = model.titleArg?.let { stringResource(model.titleRes, it) }
                    ?: stringResource(model.titleRes),
                color = palette.fg,
                style = MaterialTheme.typography.bodySmall,
            )
            model.detailRes?.let { detailRes ->
                Text(
                    text = model.detailArg?.let { stringResource(detailRes, it) }
                        ?: stringResource(detailRes),
                    color = palette.fg,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        if (model.action != null && model.actionLabelRes != null) {
            AppSecondaryButton(
                text = stringResource(model.actionLabelRes),
                leadingIcon = if (model.action == PendingEnrichmentBandAction.RetryObservation) {
                    Icons.Filled.Refresh
                } else {
                    null
                },
                onClick = when (model.action) {
                    PendingEnrichmentBandAction.OpenExpense -> onOpenFeedbackExpense
                    PendingEnrichmentBandAction.RetryObservation -> onRetryObservation
                },
            )
        }
    }
}

private fun bandIcon(kind: PendingEnrichmentFeedbackKind?): ImageVector = when (kind) {
    null -> Icons.Filled.AutoFixHigh
    PendingEnrichmentFeedbackKind.Updated -> Icons.Filled.Check
    PendingEnrichmentFeedbackKind.NoResult -> Icons.Filled.Edit
    PendingEnrichmentFeedbackKind.Failed -> Icons.Filled.ErrorOutline
    PendingEnrichmentFeedbackKind.Conflict,
    PendingEnrichmentFeedbackKind.Cancelled,
    PendingEnrichmentFeedbackKind.NotPending,
    PendingEnrichmentFeedbackKind.Unavailable,
    -> Icons.Filled.Info
}

private fun StateTokens.forBandTone(tone: PendingEnrichmentBandTone): StateTone = when (tone) {
    PendingEnrichmentBandTone.Info -> info
    PendingEnrichmentBandTone.Success -> success
    PendingEnrichmentBandTone.Warn -> warn
    PendingEnrichmentBandTone.Danger -> danger
    PendingEnrichmentBandTone.Neutral -> neutral
}
