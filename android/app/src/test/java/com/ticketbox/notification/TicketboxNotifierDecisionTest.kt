package com.ticketbox.notification

import com.ticketbox.R
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

/**
 * 通知闭环 PR-1/PR-2：[decideDraftNotification] 决策矩阵 + [draftNotificationContentSpec] /
 * [recurringNotificationContentSpec] 内容规格的纯 JVM 测试（零 Android 依赖——顶层函数直测，
 * 资源用 R.string.* 的 Int id 对账，不加载任何 Android 绑定类、不解析字符串）。
 */
class TicketboxNotifierDecisionTest {

    @Test
    fun thresholdIsFiveHundredYuanLiteral() {
        // 字面量钉:其余测试都引用常量(常量变测试输入跟着变,自指不咬),
        // 这里钉死数值本身——阈值改动必须同步「金额达到 ¥500 时提醒」副标题
        // 文案,本测试强制这次同步在同一个 diff 里发生。
        assertEquals(50_000L, LARGE_AMOUNT_THRESHOLD_CENTS)
    }

    @Test
    fun allRemindersOffYieldsNone() {
        assertEquals(
            DraftNotificationDecision.NONE,
            decideDraftNotification(
                pendingEnabled = false,
                largeEnabled = false,
                amountCents = 99_900L,
                notificationsAllowed = true,
            ),
        )
    }

    @Test
    fun pendingOnlyYieldsDraftEvenAboveThreshold() {
        // 大额开关关着时，超阈值金额也只发 DRAFT，不得越权升级成 LARGE。
        assertEquals(
            DraftNotificationDecision.DRAFT,
            decideDraftNotification(
                pendingEnabled = true,
                largeEnabled = false,
                amountCents = LARGE_AMOUNT_THRESHOLD_CENTS + 1,
                notificationsAllowed = true,
            ),
        )
    }

    @Test
    fun largeToggleAtExactThresholdYieldsLarge() {
        // 钉死 >= 边界：恰好 50_000 分（¥500）即触发大额。
        assertEquals(
            DraftNotificationDecision.LARGE,
            decideDraftNotification(
                pendingEnabled = false,
                largeEnabled = true,
                amountCents = LARGE_AMOUNT_THRESHOLD_CENTS,
                notificationsAllowed = true,
            ),
        )
    }

    @Test
    fun largeBelowThresholdWithPendingOnFallsBackToDraft() {
        assertEquals(
            DraftNotificationDecision.DRAFT,
            decideDraftNotification(
                pendingEnabled = true,
                largeEnabled = true,
                amountCents = LARGE_AMOUNT_THRESHOLD_CENTS - 1,
                notificationsAllowed = true,
            ),
        )
    }

    @Test
    fun largeOnlyBelowThresholdStaysSilent() {
        // 只开大额、未达阈值：不退化成 DRAFT，保持静默。
        assertEquals(
            DraftNotificationDecision.NONE,
            decideDraftNotification(
                pendingEnabled = false,
                largeEnabled = true,
                amountCents = LARGE_AMOUNT_THRESHOLD_CENTS - 1,
                notificationsAllowed = true,
            ),
        )
    }

    @Test
    fun systemNotificationsDisallowedYieldsNoneEvenWhenBothTogglesOn() {
        assertEquals(
            DraftNotificationDecision.NONE,
            decideDraftNotification(
                pendingEnabled = true,
                largeEnabled = true,
                amountCents = LARGE_AMOUNT_THRESHOLD_CENTS + 1,
                notificationsAllowed = false,
            ),
        )
    }

    @Test
    fun largeSwallowsDraftWhenBothTogglesApply() {
        // 吞并断言：两个开关同时命中时决策值是且仅是 LARGE——
        // 单一枚举返回值即「不双响」保证，不存在 LARGE+DRAFT 叠加态。
        assertEquals(
            DraftNotificationDecision.LARGE,
            decideDraftNotification(
                pendingEnabled = true,
                largeEnabled = true,
                amountCents = LARGE_AMOUNT_THRESHOLD_CENTS,
                notificationsAllowed = true,
            ),
        )
    }

    @Test
    fun nullAmountCanOnlyYieldDraft() {
        // 金额缺失无从判断大额：即便大额开关开着也只可能 DRAFT。
        assertEquals(
            DraftNotificationDecision.DRAFT,
            decideDraftNotification(
                pendingEnabled = true,
                largeEnabled = true,
                amountCents = null,
                notificationsAllowed = true,
            ),
        )
    }

    // ---- PR-2：内容规格（channel / 标题 format-arg / 锁屏 public 脱敏 / 去核对 action）----

    @Test
    fun draftSpecUsesDraftsChannelAndArglessTitle() {
        val spec = draftNotificationContentSpec(
            decision = DraftNotificationDecision.DRAFT,
            merchant = "便利店",
            homeAmount = "¥12.00",
            originalAmount = null,
        )
        assertEquals("ticketbox.drafts", spec.channelId)
        assertEquals(R.string.notification_draft_created_title, spec.titleRes)
        // 草稿标题无占位符：不带商家/金额 arg。
        assertEquals(emptyList(), spec.titleArgs)
        assertEquals(R.string.notification_draft_created_body, spec.bodyRes)
        assertEquals(listOf("便利店", "¥12.00"), spec.bodyArgs)
    }

    @Test
    fun largeSpecUsesAlertsChannelAndCarriesMerchantAndAmountInTitle() {
        // 拍板⑨大额标题口语化「这笔有点大：%1$s %2$s」——format-arg 必须带商家+本位币金额，
        // 这是 PR-2 把标题从无参改成带参的核心断言。
        val spec = draftNotificationContentSpec(
            decision = DraftNotificationDecision.LARGE,
            merchant = "海底捞",
            homeAmount = "¥888.00",
            originalAmount = null,
        )
        assertEquals("ticketbox.alerts", spec.channelId)
        assertEquals(R.string.notification_large_amount_title, spec.titleRes)
        assertEquals(listOf("海底捞", "¥888.00"), spec.titleArgs)
    }

    @Test
    fun draftSpecWithForeignCurrencyUsesOriginalBodyVariant() {
        val spec = draftNotificationContentSpec(
            decision = DraftNotificationDecision.DRAFT,
            merchant = "Apple",
            homeAmount = "¥7,200.00",
            originalAmount = "$999.00",
        )
        assertEquals(R.string.notification_draft_created_body_with_original, spec.bodyRes)
        assertEquals(listOf("Apple", "¥7,200.00", "$999.00"), spec.bodyArgs)
    }

    @Test
    fun draftSpecPublicSummaryIsDeIdentifiedNotTheBody() {
        // 锁屏 public 版必须用脱敏摘要资源，不能复用带商家/金额的正文资源。
        val spec = draftNotificationContentSpec(
            decision = DraftNotificationDecision.LARGE,
            merchant = "海底捞",
            homeAmount = "¥888.00",
            originalAmount = null,
        )
        assertEquals(R.string.notification_public_draft_summary, spec.publicSummaryRes)
        assertNotEquals(spec.bodyRes, spec.publicSummaryRes)
    }

    @Test
    fun everyDraftSpecCarriesReviewAction() {
        DraftNotificationDecision.entries
            .filter { it != DraftNotificationDecision.NONE }
            .forEach { decision ->
                val spec = draftNotificationContentSpec(
                    decision = decision,
                    merchant = "x",
                    homeAmount = "¥1.00",
                    originalAmount = null,
                )
                assertEquals(R.string.notification_action_review, spec.actionLabelRes)
            }
    }

    @Test
    fun draftSpecRejectsNoneDecision() {
        // NONE 应在上游短路；传进规格构造视为编程错误而非静默出一条空通知。
        assertFailsWith<IllegalArgumentException> {
            draftNotificationContentSpec(
                decision = DraftNotificationDecision.NONE,
                merchant = "x",
                homeAmount = "¥1.00",
                originalAmount = null,
            )
        }
    }

    @Test
    fun recurringSpecUsesRecurringChannelTitleArgBodyAndPublicSummary() {
        // 固定支出提醒：独立 channel；标题带固定支出名；正文无参「只做提醒…」；
        // 锁屏 public 用固定支出脱敏摘要；带去核对 action。
        val spec = recurringNotificationContentSpec(merchant = "房租")
        assertEquals("ticketbox.recurring", spec.channelId)
        assertEquals(R.string.notification_recurring_due_title, spec.titleRes)
        assertEquals(listOf("房租"), spec.titleArgs)
        assertEquals(R.string.notification_recurring_due_body, spec.bodyRes)
        assertEquals(emptyList(), spec.bodyArgs)
        assertEquals(R.string.notification_public_recurring_summary, spec.publicSummaryRes)
        assertEquals(R.string.notification_action_review, spec.actionLabelRes)
    }

    @Test
    fun threeChannelsAreDistinctStableIds() {
        // channel id 一经发布不可改；三类互不相同，避免分类串台。
        val draftChannel = draftNotificationContentSpec(
            DraftNotificationDecision.DRAFT, "a", "¥1.00", null,
        ).channelId
        val largeChannel = draftNotificationContentSpec(
            DraftNotificationDecision.LARGE, "a", "¥1.00", null,
        ).channelId
        val recurringChannel = recurringNotificationContentSpec("a").channelId
        assertEquals("ticketbox.drafts", draftChannel)
        assertEquals("ticketbox.alerts", largeChannel)
        assertEquals("ticketbox.recurring", recurringChannel)
        assertTrue(setOf(draftChannel, largeChannel, recurringChannel).size == 3)
    }
}
