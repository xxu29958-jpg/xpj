package com.ticketbox.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import kotlin.math.roundToInt

/**
 * ADR-0049 §7.0 (slice 8e ②) 成员债关系卡 —— [DebtDetailScreen] 对**成员**欠款渲染的主卡，替换会计味的
 * [DebtSummaryCard] (外部债仍用后者，一字不改)。换轴 (Communal not Market)：金额不当英雄，主视觉是
 * "一起处理这件事 → 关系进度语 → 进度条"；精确数字降到"看看账"展开区 (变 frame 不变 visibility)。
 * 状态/角色全读服务端权威 (status / [Debt.viewerIsDebtor])，客户端只算渲染比例 ([communalRatio])。
 * 独立成文件而非堆进 DebtDetailScreen.kt，避免顶破后者的文件级 TooManyFunctions 门
 * ([[project_android_compose_detekt_limits]])；复用 DebtDetailScreen 的 internal [DebtSummaryCard] /
 * [DebtSummaryRow] 与 DebtGoalLabels 的 [DebtStatusBadge]。
 */
@Composable
internal fun MemberSharedThingCard(debt: Debt, currency: CurrencyDisplay) {
    // §2.6 外币防御：成员债当前必是 home-shape (slice4 把 received Debt 冻结成严格本位币)，但若未来放开
    // 外币 member Debt，关系叙事的"无金额主句 + 单币进度"语义不再成立 → 退回会计卡的中性金额渲染。
    if (debt.originalCurrencyCode != null && debt.originalCurrencyCode != debt.homeCurrencyCode) {
        DebtSummaryCard(debt = debt, currency = currency)
        return
    }
    val ratio = communalRatio(debt.paidAmountCents, debt.principalAmountCents)
    val eyebrowName = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    val eyebrowRes = if (debt.viewerIsDebtor == null) {
        R.string.debt_member_card_eyebrow_third_party
    } else {
        R.string.debt_member_card_eyebrow
    }
    // §2.5 已作废：主句 neutral.fg + 整卡 alpha 沉降 (这件事不算了 = 平静收束，不是错误，绝不 danger)；
    // 进行中/两清主句统一 onSurface (不随比例变绿——businesslike F6)。
    val headlineColor =
        if (debt.isVoided) LocalStateTokens.current.neutral.fg else MaterialTheme.colorScheme.onSurface
    val cardModifier =
        if (debt.isVoided) Modifier.fillMaxWidth().alpha(AppAlpha.opaque) else Modifier.fillMaxWidth()
    AppGlassCard(modifier = cardModifier) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
            Text(
                stringResource(eyebrowRes, eyebrowName),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(memberDebtHeadlineRes(debt.viewerIsDebtor, debt.status, isForgiven = false, ratio = ratio)),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = headlineColor,
            )
            if (debt.isOpen) {
                Spacer(Modifier.size(AppSpacing.compactGap))
                CommunalProgressBar(ratio = ratio)
            }
            Spacer(Modifier.size(AppSpacing.compactGap))
            HorizontalDivider()
            MemberDebtDetailExpander(debt = debt, currency = currency)
        }
    }
}

/** 进度条 (open 时显示)：success-token 填充，counting-up，无百分比/无计数器/无红色 (§2.3)。 */
@Composable
private fun CommunalProgressBar(ratio: Float) {
    val tokens = LocalStateTokens.current
    val animated by animateFloatAsState(
        targetValue = ratio.coerceIn(0f, 1f),
        animationSpec = AppMotion.standardSpec(),
        label = "communalProgress",
    )
    val percent = (ratio.coerceIn(0f, 1f) * 100).roundToInt()
    val a11y = stringResource(R.string.debt_member_progress_a11y, percent)
    Column(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(AppSpacing.contentGap)
                .clip(RoundedCornerShape(AppRadius.small))
                .background(tokens.success.bg)
                .semantics { contentDescription = a11y },
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(animated)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(AppRadius.small))
                    .background(tokens.success.fg),
            )
        }
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            stringResource(memberDebtProgressNoteRes(ratio)),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** "看看账"可展开明细：只两个真实数 (一共/已对上) + 状态徽章，无 remaining 欠条行 (§2.3 businesslike F4)。 */
@Composable
private fun MemberDebtDetailExpander(debt: Debt, currency: CurrencyDisplay) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    Row(
        modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(vertical = AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            stringResource(R.string.debt_member_detail_toggle),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        Icon(
            imageVector = if (expanded) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(18.dp),
        )
    }
    AnimatedVisibility(visible = expanded) {
        Column(modifier = Modifier.fillMaxWidth()) {
            DebtSummaryRow(
                label = stringResource(R.string.debt_member_detail_total),
                value = formatDisplayAmount(debt.principalAmountCents, currency),
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            DebtSummaryRow(
                label = stringResource(R.string.debt_member_detail_paid),
                value = formatDisplayAmount(debt.paidAmountCents, currency),
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    stringResource(R.string.debt_member_detail_status),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                DebtStatusBadge(
                    text = stringResource(memberDebtStatusLabelRes(debt.status)),
                    tone = memberDebtStatusTone(debt.status),
                )
            }
        }
    }
}
