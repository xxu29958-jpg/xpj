package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseFactRevisionTimelineModelsTest {
    @Test
    fun `original amount uses each revision snapshot currency exponent`() {
        val revision = ExpenseRevision(
            publicId = "revision-2",
            revisionNumber = 2,
            changeKind = "correction",
            reason = "修正原币金额",
            changedFields = listOf("original_currency_code", "original_amount_minor"),
            before = mapOf(
                "original_currency_code" to "JPY",
                "original_amount_minor" to 1_200L,
            ),
            after = mapOf(
                "original_currency_code" to "USD",
                "original_amount_minor" to 1_200L,
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        val amountChange = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY)
            .single()
            .changes
            .single { (it.label as? UiText.Res)?.id == R.string.expense_fact_timeline_field_original_amount }

        assertEquals(UiText.raw("1200"), amountChange.before)
        assertEquals(UiText.raw("12.00"), amountChange.after)
    }

    @Test
    fun `amount-only correction derives the allocation state change from revision snapshots`() {
        val revision = ExpenseRevision(
            publicId = "revision-3",
            revisionNumber = 3,
            changeKind = "correction",
            reason = "账单金额应更高",
            changedFields = listOf("amount_cents"),
            before = mapOf(
                "amount_cents" to 1_200L,
                "splits" to listOf(mapOf("amount_cents" to 1_200L)),
            ),
            after = mapOf(
                "amount_cents" to 1_300L,
                "splits" to listOf(mapOf("amount_cents" to 1_200L)),
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        val allocationChange = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY)
            .single()
            .changes
            .single { (it.label as? UiText.Res)?.id == R.string.expense_fact_timeline_field_splits }

        assertEquals(UiText.res(R.string.expense_fact_timeline_allocation_complete), allocationChange.before)
        assertEquals(
            UiText.res(R.string.expense_fact_timeline_allocation_remaining, "1.00"),
            allocationChange.after,
        )
    }

    @Test
    fun `split correction prioritizes changed allocation over unchanged line count`() {
        val revision = ExpenseRevision(
            publicId = "revision-splits",
            revisionNumber = 4,
            changeKind = "correction",
            reason = "修正家庭拆账",
            changedFields = listOf("splits"),
            before = mapOf(
                "amount_cents" to 1_200L,
                "splits" to listOf(mapOf("amount_cents" to 1_200L)),
            ),
            after = mapOf(
                "amount_cents" to 1_200L,
                "splits" to listOf(mapOf("amount_cents" to 1_100L)),
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        val allocationChange = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY)
            .single()
            .changes
            .single()

        assertEquals(UiText.res(R.string.expense_fact_timeline_field_splits), allocationChange.label)
        assertEquals(UiText.res(R.string.expense_fact_timeline_allocation_complete), allocationChange.before)
        assertEquals(
            UiText.res(R.string.expense_fact_timeline_allocation_remaining, "1.00"),
            allocationChange.after,
        )
    }

    @Test
    fun `unknown snapshot home currency stays raw in amount and allocation history`() {
        val revision = ExpenseRevision(
            publicId = "revision-4",
            revisionNumber = 4,
            changeKind = "correction",
            reason = "修正账单金额",
            changedFields = listOf("amount_cents"),
            before = mapOf(
                "home_currency_code" to "VND",
                "amount_cents" to 1_200L,
                "splits" to listOf(mapOf("amount_cents" to 1_200L)),
            ),
            after = mapOf(
                "home_currency_code" to "VND",
                "amount_cents" to 1_300L,
                "splits" to listOf(mapOf("amount_cents" to 1_200L)),
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        val changes = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY)
            .single()
            .changes

        val amountChange = changes.single {
            (it.label as? UiText.Res)?.id == R.string.expense_fact_timeline_field_amount
        }
        val allocationChange = changes.single {
            (it.label as? UiText.Res)?.id == R.string.expense_fact_timeline_field_splits
        }

        assertEquals(UiText.raw("1200 VND"), amountChange.before)
        assertEquals(UiText.raw("1300 VND"), amountChange.after)
        assertEquals(UiText.res(R.string.expense_fact_timeline_allocation_complete), allocationChange.before)
        assertEquals(
            UiText.res(R.string.expense_fact_timeline_allocation_remaining, "100 VND"),
            allocationChange.after,
        )
    }

    @Test
    fun `items correction keeps the count summary and exposes full before and after sets`() {
        val milkBefore = mapOf(
            "position" to 0,
            "name" to "牛奶",
            "quantity_text" to "x2",
            "unit_price_cents" to 1_200L,
            "amount_cents" to 2_400L,
            "category" to "食品",
        )
        val revision = ExpenseRevision(
            publicId = "revision-items",
            revisionNumber = 5,
            changeKind = "correction",
            reason = "补登一行小票",
            changedFields = listOf("items"),
            before = mapOf("items" to listOf(milkBefore)),
            after = mapOf(
                "items" to listOf(
                    milkBefore,
                    mapOf("position" to 1, "name" to "面包", "amount_cents" to 600L),
                ),
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        val entry = listOf(revision).toTimelineEntries(CurrencyCode.CNY).single()

        // 紧凑计数摘要保留
        val countChange = entry.changes.single {
            (it.label as? UiText.Res)?.id == R.string.expense_fact_timeline_field_items
        }
        assertEquals(UiText.res(R.string.expense_fact_timeline_lines_count, 1), countChange.before)
        assertEquals(UiText.res(R.string.expense_fact_timeline_lines_count, 2), countChange.after)

        // 完整 Before/After 集合：不做行级 diff，两行各自完整呈现快照已有字段
        val detail = entry.collections.single {
            it.labelRes == R.string.expense_fact_timeline_field_items
        }
        assertEquals(1, detail.beforeRows.size)
        assertEquals(2, detail.afterRows.size)

        val milk = detail.beforeRows.single()
        assertEquals(UiText.raw("牛奶"), milk.title)
        assertEquals(
            listOf(
                UiText.raw("x2"),
                UiText.res(R.string.expense_fact_timeline_item_unit_price, "12.00"),
                UiText.res(R.string.expense_fact_timeline_item_amount, "24.00"),
                UiText.raw("食品"),
            ),
            milk.facts,
        )

        val bread = detail.afterRows[1]
        assertEquals(UiText.raw("面包"), bread.title)
        assertEquals(
            listOf(UiText.res(R.string.expense_fact_timeline_item_amount, "6.00")),
            bread.facts,
        )
    }

    @Test
    fun `splits correction shows current member names and honest removed fallback`() {
        val revision = ExpenseRevision(
            publicId = "revision-split-rows",
            revisionNumber = 6,
            changeKind = "correction",
            reason = "调整拆账比例",
            changedFields = listOf("splits"),
            before = mapOf(
                "amount_cents" to 3_000L,
                "splits" to listOf(
                    mapOf("position" to 0, "member_id" to 7L, "amount_cents" to 2_000L),
                    mapOf("position" to 1, "member_id" to 8L, "amount_cents" to 1_000L, "note" to "垫付"),
                ),
            ),
            after = mapOf(
                "amount_cents" to 3_000L,
                "splits" to listOf(
                    mapOf("position" to 0, "member_id" to 7L, "amount_cents" to 1_500L),
                    mapOf("position" to 1, "member_id" to 8L, "amount_cents" to 1_500L, "note" to "垫付"),
                ),
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        val detail = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY, memberNames = mapOf(7L to "爸爸"))
            .single()
            .collections
            .single { it.labelRes == R.string.expense_fact_timeline_field_splits }

        val beforeRows = detail.beforeRows
        assertEquals(2, beforeRows.size)
        // member_id 命中当前目录 → 当前显示名
        assertEquals(UiText.raw("爸爸"), beforeRows[0].title)
        assertEquals(listOf(UiText.raw("20.00")), beforeRows[0].facts)
        // member_id 未命中已加载目录 → 诚实「已移除的成员」，金额/备注仍呈现
        assertEquals(UiText.res(R.string.expense_fact_timeline_member_removed), beforeRows[1].title)
        assertEquals(listOf(UiText.raw("10.00"), UiText.raw("垫付")), beforeRows[1].facts)
    }

    @Test
    fun `splits rows stay neutral when the member directory is unavailable`() {
        val revision = ExpenseRevision(
            publicId = "revision-split-no-directory",
            revisionNumber = 7,
            changeKind = "correction",
            reason = "调整拆账",
            changedFields = listOf("splits"),
            before = mapOf(
                "amount_cents" to 3_000L,
                "splits" to listOf(mapOf("position" to 0, "member_id" to 7L, "amount_cents" to 3_000L)),
            ),
            after = mapOf(
                "amount_cents" to 3_000L,
                "splits" to listOf(mapOf("position" to 0, "member_id" to 7L, "amount_cents" to 2_000L)),
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        // null = 目录未加载/加载失败：不得谎称「已移除」，退化为中性标签
        val unavailable = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY, memberNames = null)
            .single()
            .collections
            .single { it.labelRes == R.string.expense_fact_timeline_field_splits }
        assertEquals(
            UiText.res(R.string.expense_fact_timeline_member_unknown),
            unavailable.beforeRows.single().title,
        )
        assertEquals(listOf(UiText.raw("30.00")), unavailable.beforeRows.single().facts)

        // non-null（哪怕 emptyMap）= 目录成功：id 不命中才显示「已移除的成员」
        val emptyDirectory = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY, memberNames = emptyMap())
            .single()
            .collections
            .single { it.labelRes == R.string.expense_fact_timeline_field_splits }
        assertEquals(
            UiText.res(R.string.expense_fact_timeline_member_removed),
            emptyDirectory.beforeRows.single().title,
        )
    }
}
