package com.ticketbox.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import kotlin.math.roundToInt

/** Member relationship summary: identify the other party and the remaining frozen amount before acting. */
@Composable
internal fun MemberSharedThingCard(debt: Debt) {
    // The shared summary retains both currencies when the record carries an original foreign amount.
    if (debt.originalCurrencyCode != null && debt.originalCurrencyCode != debt.homeCurrencyCode) {
        DebtSummaryCard(debt = debt)
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
    AppPaperCard(modifier = cardModifier) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
            Text(
                stringResource(eyebrowRes, eyebrowName),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(memberDebtHeadlineRes(debt.viewerIsDebtor, debt.status, isForgiven = debt.isForgiven, ratio = ratio)),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = headlineColor,
            )
            Spacer(Modifier.size(AppSpacing.compactGap))
            DebtSummaryRow(
                label = stringResource(R.string.debt_detail_remaining),
                value = formatDisplayAmount(debt.remainingAmountCents, CurrencyDisplay.forRecord(debt.homeCurrencyCode)),
            )
            if (debt.isOpen) {
                Spacer(Modifier.size(AppSpacing.compactGap))
                CommunalProgressBar(ratio = ratio)
            }
            Spacer(Modifier.size(AppSpacing.compactGap))
            HorizontalDivider()
            MemberDebtDetailExpander(debt = debt)
        }
    }
}

/** 进度条 (open 时显示)：success-token 填充，counting-up，无百分比/无计数器/无红色 (§2.3)。委托通用 [AppProgressBar]
 * (8e-5 抽出，视觉逐字节不变)，下方再缀一句无数字程度语。 */
@Composable
private fun CommunalProgressBar(ratio: Float) {
    val tokens = LocalStateTokens.current
    val percent = (ratio.coerceIn(0f, 1f) * 100).roundToInt()
    val a11y = stringResource(R.string.debt_member_progress_a11y, percent)
    Column(modifier = Modifier.fillMaxWidth()) {
        AppProgressBar(
            fraction = ratio,
            tone = tokens.success,
            height = AppSpacing.contentGap,
            contentDescription = a11y,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            stringResource(memberDebtProgressNoteRes(ratio)),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** Supporting totals and status remain available beneath the always-visible remaining amount. */
@Composable
private fun MemberDebtDetailExpander(debt: Debt) {
    // 与 DebtSummaryCard 同一 record 口径（PR#255 R5 P1）：环境 display 恒 Base，必须按
    // debt.homeCurrencyCode 渲染，否则 JPY/KRW 欠款金额小数位走样。
    val recordDisplay = CurrencyDisplay.forRecord(debt.homeCurrencyCode)
    var expanded by rememberSaveable(debt.publicId) { mutableStateOf(false) }
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
                value = formatDisplayAmount(debt.principalAmountCents, recordDisplay),
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            DebtSummaryRow(
                label = stringResource(R.string.debt_member_detail_paid),
                value = formatDisplayAmount(debt.paidAmountCents, recordDisplay),
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
