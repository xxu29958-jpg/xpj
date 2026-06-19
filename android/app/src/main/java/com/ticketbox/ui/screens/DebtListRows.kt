package com.ticketbox.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import kotlin.math.roundToInt

/**
 * ADR-0049 §7.0 (slice 1A) 欠款列表的**按角色分轴**行件 + 软分组。
 *
 * 成员债 = communal 关系行 ([MemberDebtRow])：对手方名 + viewer-相对关系主句(无金额) + open 时细
 * success 进度条 + 状态徽章(neutral/success **永不 danger** 红线②)，作废/已结清沉降。外部债仍走
 * [DebtListScreen] 里的会计行 (应付/应收 + 剩余英雄)，一字不改。关系主句逐字复用详情的
 * [memberDebtHeadlineRes] (列表↔详情同一句，点进详情不变脸)，不另造平行 copy 集。
 *
 * 角色读服务端权威 [Debt.viewerIsDebtor] (列表路由现也 per-row 填充)，不从 owner-相对 `direction`
 * 推 (会对非当事方 viewer 翻错)、不客户端推导 (红线⑥)。独立成文件避免顶破 [DebtListScreen] 的文件级
 * TooManyFunctions 门 ([[project_android_compose_detekt_limits]])。
 */

/** 行内状态排序权重：未结清在前，已结清/作废沉到底 (active-first，镜像 web `_STATUS_RANK`)。 */
private fun debtRowStatusRank(status: String): Int = when (status) {
    DebtLinkStatuses.OPEN -> 0
    DebtLinkStatuses.CLEARED -> 1
    else -> 2 // voided / 未知
}

/** 是否走 communal 家人行：成员债且 home-shape (外币成员债退回外部会计行，镜像详情/web 的 FX 防御)。 */
private fun isCommunalRow(debt: Debt): Boolean {
    val foreign = debt.originalCurrencyCode != null && debt.originalCurrencyCode != debt.homeCurrencyCode
    return debt.isMember && !foreign
}

/**
 * 把欠款列表分成 (家人, 外部) 两组，各组 active-first 排序 (open 在前，cleared/voided 沉底)。纯函数、
 * 可单测、镜像 web `_split_debt_views`。Kotlin [sortedBy] 稳定 → 同档内保留服务端返回的 created 次序。
 */
internal fun groupDebtsForList(debts: List<Debt>): Pair<List<Debt>, List<Debt>> {
    val (members, externals) = debts.partition { isCommunalRow(it) }
    return members.sortedBy { debtRowStatusRank(it.status) } to externals.sortedBy { debtRowStatusRank(it.status) }
}

/** 软分组标题 (section header 非 tab)：家人在前，单滚动列表。无聚合记分牌 (禁 per-person/总额)。 */
@Composable
internal fun DebtSectionHeader(title: String) {
    Text(
        title,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = AppSpacing.smallGap, bottom = AppSpacing.miniGap),
    )
}

/**
 * 家人(成员)债 communal 行：对手方名(行1) + viewer-相对关系主句(行2，无金额) + open 时细 success 进度条
 * + 右侧状态徽章 (neutral/success 永不红)。已结清/作废沉降 (alpha，办完可追溯)。精确数留详情「看看账」。
 *
 * [onClick] 为 null 时是**静态(不可点)**行——跨账本应收(⑤c-2)是只读发现面，镜像 web 的 `.dt-card--static`
 * (还款由债务人在手机 App 发起、债权人确认，§7.0 命名要对上的人但不催)。欠款列表传入 tap 进详情。
 */
@Composable
internal fun MemberDebtRow(debt: Debt, onClick: (() -> Unit)? = null) {
    val name = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    val ratio = communalRatio(debt.paidAmountCents, debt.principalAmountCents)
    // 已结清/作废 = 平静收束，视觉沉降 (镜像 MemberSharedThingCard 的 voided 沉降，永不红)。
    val cardModifier =
        if (debt.isOpen) Modifier.fillMaxWidth() else Modifier.fillMaxWidth().alpha(AppAlpha.opaque)
    val rowModifier = Modifier
        .fillMaxWidth()
        .let { if (onClick != null) it.clickable(onClick = onClick) else it }
        .padding(AppSpacing.cardPadding)
    AppGlassCard(modifier = cardModifier) {
        Row(
            modifier = rowModifier,
            verticalAlignment = Alignment.Top,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.size(AppSpacing.smallGap))
                Text(
                    stringResource(
                        memberDebtHeadlineRes(
                            debt.viewerIsDebtor,
                            debt.status,
                            isForgiven = debt.isForgiven,
                            ratio = ratio,
                        ),
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (debt.isOpen) {
                    Spacer(Modifier.size(AppSpacing.compactGap))
                    val percent = (ratio.coerceIn(0f, 1f) * 100).roundToInt()
                    AppProgressBar(
                        fraction = ratio,
                        tone = LocalStateTokens.current.success,
                        height = AppSpacing.miniGap, // 4dp，对齐 web 列表行 .debt-progress--row 的 --space-2(4px)
                        contentDescription = stringResource(R.string.debt_member_progress_a11y, percent),
                    )
                }
            }
            Spacer(Modifier.width(AppSpacing.smallGap))
            DebtStatusBadge(
                text = stringResource(memberDebtStatusLabelRes(debt.status)),
                tone = memberDebtStatusTone(debt.status),
            )
        }
    }
}
