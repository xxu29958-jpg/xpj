package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import com.ticketbox.R
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTone

/**
 * ADR-0049 §7.0 (slice 8e ②) 成员债关系化 (Communal not Market) 的纯 `@StringRes` 映射 + 状态色调。
 *
 * 与外部债的会计映射 ([debtDirectionLabelRes] / [debtLinkStatusLabelRes] / [debtLinkStatusTone],
 * 在 [DebtGoalLabels] 里，**8e 不动**) 平行而独立：成员债换一根轴——方向叙述成"帮垫"善意、进度叙述成
 * "对上/两清"关系、状态色调**恒 neutral/success、绝不 danger** (红线②：成员债不 shame)。状态/角色全读
 * 服务端权威 (status / [com.ticketbox.domain.model.Debt.viewerIsDebtor])，客户端只算渲染比例
 * ([communalRatio])，不从 `remaining==0` 推导状态 (红线⑥)。纯函数，可单测 (镜像 [DebtGoalLabels])。
 */

/** 进度条比例 = paid/principal，纯渲染算术 (服务端冻结的 paid/principal，不读活余额)，钳到 [0,1]。 */
internal fun communalRatio(paidCents: Long, principalCents: Long): Float =
    if (principalCents <= 0L) 0f else (paidCents.toFloat() / principalCents.toFloat()).coerceIn(0f, 1f)

/** 进度跨入"快两清"档的门槛 (§2.3 近末 ratio≥0.7)。 */
private const val MEMBER_DEBT_NEAR_RATIO = 0.7f

/** 进度跨入"已对上一部分"档的门槛 (§2.3 程度语 ≤0.5 some / >0.5 most)。 */
private const val MEMBER_DEBT_SOME_RATIO = 0.5f

/**
 * Header 副标题 / 方向 (viewer-relative，§2.3)：`true`=你帮我垫的、`false`=我帮你垫的、
 * `null`=第三人称 (非当事方)。外部债仍走 [debtDirectionLabelRes] 应付/应收。
 */
@StringRes
internal fun memberDebtDirectionRes(viewerIsDebtor: Boolean?): Int = when (viewerIsDebtor) {
    true -> R.string.debt_member_direction_i_owe
    false -> R.string.debt_member_direction_owed_to_me
    null -> R.string.debt_member_direction_third_party
}

/**
 * 关系进度语英雄主句 (无金额，§2.3)。状态全读服务端：`status` (open/cleared/voided)、`isForgiven`
 * (8e-2 恒 false——`Debt` 尚无 forgiveness 字段，8e-3 forgive op 落地后接线)、`viewerIsDebtor`。
 * forgiven 落地态是 `cleared` (非 voided)，故 forgiven 分支挂在 cleared 下，用专属暖语而非复用两清。
 */
@StringRes
internal fun memberDebtHeadlineRes(
    viewerIsDebtor: Boolean?,
    status: String,
    isForgiven: Boolean,
    ratio: Float,
): Int = when {
    // 非当事方：第三人称中性档 (§2.5)。
    viewerIsDebtor == null -> when (status) {
        DebtLinkStatuses.CLEARED -> R.string.debt_member_headline_third_party_cleared
        DebtLinkStatuses.VOIDED -> R.string.debt_member_headline_voided
        else -> R.string.debt_member_headline_third_party_progress
    }
    status == DebtLinkStatuses.VOIDED -> R.string.debt_member_headline_voided
    status == DebtLinkStatuses.CLEARED -> when {
        isForgiven && viewerIsDebtor -> R.string.debt_member_headline_forgiven_debtor
        isForgiven -> R.string.debt_member_headline_forgiven_creditor
        else -> R.string.debt_member_headline_cleared
    }
    // open：按进度比例分三档，viewerIsDebtor 在此已非空 (前面的 == null 分支已排除)。
    else -> openMemberDebtHeadlineRes(ratio = ratio, iOwe = viewerIsDebtor)
}

/** open 成员债主句的进度三档 (start/early/near)，i_owe (债务人视角) 与 owed_to_me (债权人视角) 各一套措辞。 */
@StringRes
private fun openMemberDebtHeadlineRes(ratio: Float, iOwe: Boolean): Int = when {
    ratio <= 0f ->
        if (iOwe) R.string.debt_member_headline_i_owe_start else R.string.debt_member_headline_owed_start
    ratio < MEMBER_DEBT_NEAR_RATIO ->
        if (iOwe) R.string.debt_member_headline_i_owe_early else R.string.debt_member_headline_owed_early
    else ->
        if (iOwe) R.string.debt_member_headline_i_owe_near else R.string.debt_member_headline_owed_near
}

/** 进度条下的程度语 (无百分比/无计数器，§2.3)。cleared/voided 不显示条，故该函数只在 open 调用。 */
@StringRes
internal fun memberDebtProgressNoteRes(ratio: Float): Int = when {
    ratio <= 0f -> R.string.debt_member_progress_none
    ratio <= MEMBER_DEBT_SOME_RATIO -> R.string.debt_member_progress_some
    else -> R.string.debt_member_progress_most
}

/** "看看账"明细里的成员债状态徽章文案 (外部债 [debtLinkStatusLabelRes] 不动)。 */
@StringRes
internal fun memberDebtStatusLabelRes(status: String): Int = when (status) {
    DebtLinkStatuses.OPEN -> R.string.debt_member_status_open
    DebtLinkStatuses.CLEARED -> R.string.debt_member_status_cleared
    DebtLinkStatuses.VOIDED -> R.string.debt_member_status_voided
    else -> R.string.debt_member_status_open
}

/**
 * 成员债状态色调档 (纯函数，可单测红线②"绝不 danger")：cleared→success (两清是好事)，其余
 * (open / voided / 未知) 一律 neutral。voided 用 neutral 而非 danger——"这件事不算了"不是错误/坏事。
 */
internal enum class MemberDebtTone { Neutral, Success }

internal fun memberDebtToneKind(status: String): MemberDebtTone = when (status) {
    DebtLinkStatuses.CLEARED -> MemberDebtTone.Success
    else -> MemberDebtTone.Neutral
}

/** [memberDebtToneKind] 的色解析 (@Composable，镜像 [debtLinkStatusTone] 但 voided→neutral 不 danger)。 */
@Composable
internal fun memberDebtStatusTone(status: String): StateTone {
    val tokens = LocalStateTokens.current
    return when (memberDebtToneKind(status)) {
        MemberDebtTone.Success -> tokens.success
        MemberDebtTone.Neutral -> tokens.neutral
    }
}
