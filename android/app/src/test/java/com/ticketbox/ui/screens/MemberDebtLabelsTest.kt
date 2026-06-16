package com.ticketbox.ui.screens

import com.ticketbox.R
import com.ticketbox.domain.model.DebtLinkStatuses
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * ADR-0049 §7.0 (slice 8e ②) 成员债关系化纯映射的单测 (镜像 [DebtGoalLabelsTest])。
 * 重点钉死两条红线：① 状态/角色/forgiven 全读服务端权威 (不从 ratio 推 status)；
 * ② 状态色调**绝不 danger** (voided 也是 neutral，成员债不 shame)。
 */
class MemberDebtLabelsTest {

    @Test
    fun communalRatioClampsAndGuardsZeroPrincipal() {
        assertEquals(0f, communalRatio(paidCents = 0, principalCents = 12_000))
        assertEquals(0.5f, communalRatio(paidCents = 6_000, principalCents = 12_000))
        // 本金为 0 不除零；超额偿还钳到 1。
        assertEquals(0f, communalRatio(paidCents = 100, principalCents = 0))
        assertEquals(1f, communalRatio(paidCents = 13_000, principalCents = 12_000))
    }

    @Test
    fun memberDirectionMapsViewerRole() {
        assertEquals(R.string.debt_member_direction_i_owe, memberDebtDirectionRes(viewerIsDebtor = true))
        assertEquals(R.string.debt_member_direction_owed_to_me, memberDebtDirectionRes(viewerIsDebtor = false))
        assertEquals(R.string.debt_member_direction_third_party, memberDebtDirectionRes(viewerIsDebtor = null))
    }

    @Test
    fun headlineThirdPartyUsesNeutralVoice() {
        val open = memberDebtHeadlineRes(null, DebtLinkStatuses.OPEN, isForgiven = false, ratio = 0.4f)
        val cleared = memberDebtHeadlineRes(null, DebtLinkStatuses.CLEARED, isForgiven = false, ratio = 1f)
        val voided = memberDebtHeadlineRes(null, DebtLinkStatuses.VOIDED, isForgiven = false, ratio = 0.4f)
        assertEquals(R.string.debt_member_headline_third_party_progress, open)
        assertEquals(R.string.debt_member_headline_third_party_cleared, cleared)
        assertEquals(R.string.debt_member_headline_voided, voided)
    }

    @Test
    fun headlineClearedAndVoidedReadServerStatusNotRatio() {
        // voided 主句不看比例 (服务端权威，红线⑥)。
        assertEquals(
            R.string.debt_member_headline_voided,
            memberDebtHeadlineRes(true, DebtLinkStatuses.VOIDED, isForgiven = false, ratio = 1f),
        )
        // cleared 非 forgiven → 两清；forgiven 走专属暖语 (debtor/creditor 分视角)。
        assertEquals(
            R.string.debt_member_headline_cleared,
            memberDebtHeadlineRes(true, DebtLinkStatuses.CLEARED, isForgiven = false, ratio = 1f),
        )
        assertEquals(
            R.string.debt_member_headline_forgiven_debtor,
            memberDebtHeadlineRes(true, DebtLinkStatuses.CLEARED, isForgiven = true, ratio = 1f),
        )
        assertEquals(
            R.string.debt_member_headline_forgiven_creditor,
            memberDebtHeadlineRes(false, DebtLinkStatuses.CLEARED, isForgiven = true, ratio = 1f),
        )
    }

    @Test
    fun headlineOpenByDirectionAndRatioTiers() {
        // i_owe (债务人视角)：start / early / near 三档。
        assertEquals(
            R.string.debt_member_headline_i_owe_start,
            memberDebtHeadlineRes(true, DebtLinkStatuses.OPEN, isForgiven = false, ratio = 0f),
        )
        assertEquals(
            R.string.debt_member_headline_i_owe_early,
            memberDebtHeadlineRes(true, DebtLinkStatuses.OPEN, isForgiven = false, ratio = 0.3f),
        )
        assertEquals(
            R.string.debt_member_headline_i_owe_near,
            memberDebtHeadlineRes(true, DebtLinkStatuses.OPEN, isForgiven = false, ratio = 0.8f),
        )
        // owed_to_me (债权人视角)：另一套措辞。
        assertEquals(
            R.string.debt_member_headline_owed_start,
            memberDebtHeadlineRes(false, DebtLinkStatuses.OPEN, isForgiven = false, ratio = 0f),
        )
        assertEquals(
            R.string.debt_member_headline_owed_near,
            memberDebtHeadlineRes(false, DebtLinkStatuses.OPEN, isForgiven = false, ratio = 0.9f),
        )
    }

    @Test
    fun progressNoteByRatioTiers() {
        assertEquals(R.string.debt_member_progress_none, memberDebtProgressNoteRes(0f))
        assertEquals(R.string.debt_member_progress_some, memberDebtProgressNoteRes(0.5f))
        assertEquals(R.string.debt_member_progress_most, memberDebtProgressNoteRes(0.51f))
    }

    @Test
    fun statusLabelAndToneNeverDanger() {
        assertEquals(R.string.debt_member_status_open, memberDebtStatusLabelRes("open"))
        assertEquals(R.string.debt_member_status_cleared, memberDebtStatusLabelRes("cleared"))
        assertEquals(R.string.debt_member_status_voided, memberDebtStatusLabelRes("voided"))
        assertEquals(R.string.debt_member_status_open, memberDebtStatusLabelRes("future_status"))
        // 红线②：cleared→Success，其余 (含 voided) 一律 Neutral，绝不 danger。
        assertEquals(MemberDebtTone.Success, memberDebtToneKind("cleared"))
        assertEquals(MemberDebtTone.Neutral, memberDebtToneKind("open"))
        assertEquals(MemberDebtTone.Neutral, memberDebtToneKind("voided"))
        assertEquals(MemberDebtTone.Neutral, memberDebtToneKind("future_status"))
    }
}
