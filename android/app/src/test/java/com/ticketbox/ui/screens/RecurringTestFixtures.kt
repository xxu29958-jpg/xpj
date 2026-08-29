package com.ticketbox.ui.screens

import com.ticketbox.domain.model.RecurringItem

/**
 * RecurringItem 测试 fixture：22 字段的 domain model 用一个 var-builder 收敛，
 * 测试只写自己在乎的字段（`recurringItem { status = "paused" }`），
 * 消灭命名参数长龙；默认值就是一条 active / manual / occurrence=0 的手工项。
 */
internal class RecurringItemFixture {
    var publicId: String = "rec-1"
    var merchant: String = "宽带"
    var baselineAmountCents: Long = 120_00
    var occurrenceCount: Int = 0
    var lastSeenAt: String? = null
    var nextExpectedDate: String? = "2026-09-01"
    var status: String = "active"
    var source: String = "manual"
    var anomalyStatus: String = "none"
    var amountDeltaPercent: Int? = null
    var rowVersion: Long = 1L

    fun build(): RecurringItem = RecurringItem(
        publicId = publicId,
        ledgerId = "ledger-1",
        merchant = merchant,
        merchantKey = merchant.lowercase(),
        frequency = "monthly",
        baselineAmountCents = baselineAmountCents,
        lastAmountCents = baselineAmountCents,
        occurrenceCount = occurrenceCount,
        lastSeenAt = lastSeenAt,
        nextExpectedDate = nextExpectedDate,
        status = status,
        confidence = null,
        source = source,
        anomalyStatus = anomalyStatus,
        currentMonthAmountCents = null,
        historicalAverageAmountCents = null,
        amountDeltaPercent = amountDeltaPercent,
        createdAt = "2026-08-01T00:00:00Z",
        updatedAt = "2026-08-01T00:00:00Z",
        rowVersion = rowVersion,
        pausedAt = null,
        archivedAt = null,
    )
}

internal fun recurringItem(configure: RecurringItemFixture.() -> Unit = {}): RecurringItem =
    RecurringItemFixture().apply(configure).build()
