package com.ticketbox.notification

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * 通知闭环 PR-1：[decideDraftNotification] 决策矩阵的纯 JVM 测试
 * （零 Android 依赖——顶层函数直测，不加载任何 Android 绑定类）。
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
}
