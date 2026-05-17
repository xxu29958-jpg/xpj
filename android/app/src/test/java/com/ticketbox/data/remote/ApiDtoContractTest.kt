package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.BudgetCategoryRequestDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.DashboardCardUpdateRequestDto
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.NotificationDraftRequestDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class ApiDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun statusDtoParsesRuleDeleteResponse() {
        val dto = requireNotNull(
            moshi.adapter(StatusDto::class.java).fromJson("""{"status":"ok"}"""),
        )

        assertEquals("ok", dto.status)
    }

    @Test
    fun uploadResponseDtoParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(UploadResponseDto::class.java).fromJson(
                """
                {
                  "id": 1,
                  "public_id": "018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d",
                  "status": "pending",
                  "message": "uploaded",
                  "image_hash": "sha256",
                  "thumbnail_path": "uploads/owner/2026/05/thumbs/example.jpg",
                  "duplicate_status": "none",
                  "duplicate_of_id": null,
                  "upload_size_bytes": 348120,
                  "duration_ms": 86,
                  "timing_ms": {
                    "form_parse_ms": 8,
                    "file_save_ms": 18,
                    "db_create_ms": 24,
                    "total_ms": 86
                  }
                }
                """.trimIndent(),
            ),
        )

        assertEquals(1L, dto.id)
        assertEquals("018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d", dto.publicId)
        assertEquals(348120L, dto.uploadSizeBytes)
        assertEquals(86L, dto.durationMs)
        assertEquals(24L, dto.timingMs?.get("db_create_ms"))
    }

    @Test
    fun notificationDraftRequestSerializesStructuredFieldsOnly() {
        val json = moshi.adapter(NotificationDraftRequestDto::class.java).toJson(
            NotificationDraftRequestDto(
                source = "wechat",
                originalCurrency = "CNY",
                originalAmount = "26.80",
                spentAt = "2026-05-13T10:05:00Z",
                merchant = "星巴克",
                category = "餐饮",
                expenseTime = "2026-05-13T10:05:00Z",
            ),
        )

        assertEquals(
            """{"source":"wechat","original_currency":"CNY","original_amount":"26.80","spent_at":"2026-05-13T10:05:00Z","merchant":"星巴克","category":"餐饮","expense_time":"2026-05-13T10:05:00Z"}""",
            json,
        )
        assertFalse(json.contains("raw_text"))
        assertFalse(json.contains("amount_cents"))
        assertFalse(json.contains("exchange_rate"))
    }

    @Test
    fun expenseItemsParsesCurrentServerShapeAndSerializesReplace() {
        val dto = requireNotNull(
            moshi.adapter(ExpenseItemsResponseDto::class.java).fromJson(
                """
                {
                  "expense_id": 1,
                  "parent_amount_cents": 1500,
                  "items_total_amount_cents": 1250,
                  "mismatch_cents": 250,
                  "items": [
                    {
                      "public_id": "item-1",
                      "position": 0,
                      "name": "拿铁",
                      "quantity_text": "1杯",
                      "unit_price_cents": 500,
                      "amount_cents": 500,
                      "category": "餐饮",
                      "raw_text": "拿铁 1杯 5.00",
                      "confidence": 0.92,
                      "is_ocr_draft": true,
                      "created_at": "2026-05-03T04:20:00Z",
                      "updated_at": "2026-05-03T04:20:00Z"
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val requestJson = moshi.adapter(ExpenseItemReplaceRequestDto::class.java).toJson(
            ExpenseItemReplaceRequestDto(
                items = listOf(
                    ExpenseItemRequestDto(
                        name = "拿铁",
                        quantityText = "1杯",
                        unitPriceCents = 500,
                        amountCents = 500,
                        category = "餐饮",
                        rawText = "拿铁 1杯 5.00",
                        confidence = 0.92,
                    ),
                ),
            ),
        )

        val item = dto.items.single()
        assertEquals("item-1", item.publicId)
        assertEquals(250L, dto.mismatchCents)
        assertEquals(true, item.isOcrDraft)
        assertEquals(
            """{"items":[{"name":"拿铁","quantity_text":"1杯","unit_price_cents":500,"amount_cents":500,"category":"餐饮","raw_text":"拿铁 1杯 5.00","confidence":0.92}]}""",
            requestJson,
        )
    }

    @Test
    fun expenseSplitsParsesCurrentServerShapeAndSerializesReplace() {
        val dto = requireNotNull(
            moshi.adapter(ExpenseSplitsResponseDto::class.java).fromJson(
                """
                {
                  "expense_id": 1,
                  "parent_amount_cents": 10000,
                  "splits_total_amount_cents": 9000,
                  "mismatch_cents": 1000,
                  "splits": [
                    {
                      "public_id": "split-1",
                      "position": 0,
                      "member_id": 12,
                      "account_name": "我",
                      "role": "owner",
                      "amount_cents": 6000,
                      "note": "我出大头",
                      "disabled_at": null,
                      "created_at": "2026-05-03T04:20:00Z",
                      "updated_at": "2026-05-03T04:20:00Z"
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val requestJson = moshi.adapter(ExpenseSplitReplaceRequestDto::class.java).toJson(
            ExpenseSplitReplaceRequestDto(
                splits = listOf(
                    ExpenseSplitRequestDto(
                        memberId = 12,
                        amountCents = 6000,
                        note = "我出大头",
                    ),
                ),
            ),
        )

        val split = dto.splits.single()
        assertEquals("split-1", split.publicId)
        assertEquals(1000L, dto.mismatchCents)
        assertEquals("owner", split.role)
        assertEquals(
            """{"splits":[{"member_id":12,"amount_cents":6000,"note":"我出大头"}]}""",
            requestJson,
        )
    }

    @Test
    fun serverSettingsDtoParsesLedgerScopeFields() {
        val dto = requireNotNull(
            moshi.adapter(ServerSettingsDto::class.java).fromJson(
                """
                {
                  "account_name": "我",
                  "ledger_id": "owner",
                  "ledger_name": "我的小票夹",
                  "ledger_is_default": true,
                  "device_name": "Pixel",
                  "role": "owner",
                  "status": "ok",
                  "storage_status": "normal",
                  "pending_count": 0,
                  "confirmed_count": 3,
                  "rejected_count": 0,
                  "suspected_duplicate_count": 0,
                  "upload_storage_bytes": 128,
                  "latest_upload_at": "2026-05-13T00:00:00Z"
                }
                """.trimIndent(),
            ),
        )

        assertEquals("owner", dto.ledgerId)
        assertEquals(true, dto.ledgerIsDefault)
    }

    @Test
    fun monthlyStatsDtoParsesTagStats() {
        val dto = requireNotNull(
            moshi.adapter(MonthlyStatsDto::class.java).fromJson(
                """
                {
                  "month": "2026-05",
                  "total_amount_cents": 15800,
                  "count": 3,
                  "by_category": [
                    {"category": "餐饮", "amount_cents": 15800, "count": 3}
                  ],
                  "by_tag": [
                    {"tag": "真香", "amount_cents": 12000, "count": 2}
                  ]
                }
                """.trimIndent(),
            ),
        )

        assertEquals("真香", dto.byTag.single().tag)
        assertEquals(12000L, dto.byTag.single().amountCents)
    }

    @Test
    fun ruleApplicationListParsesGovernanceHistory() {
        val dto = requireNotNull(
            moshi.adapter(RuleApplicationListDto::class.java).fromJson(
                """
                {
                  "items": [
                    {
                      "public_id": "batch-1",
                      "status": "applied",
                      "pending_scanned": 20,
                      "changed_count": 3,
                      "created_at": "2026-05-13T00:00:00Z",
                      "rolled_back_at": null
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )

        val item = dto.items.single()
        assertEquals("batch-1", item.publicId)
        assertEquals(20, item.pendingScanned)
        assertEquals(3, item.changedCount)
    }

    @Test
    fun categoryRuleParsesOptionalConditions() {
        val dto = requireNotNull(
            moshi.adapter(CategoryRuleDto::class.java).fromJson(
                """
                {
                  "id": 7,
                  "keyword": "Starbucks",
                  "category": "餐饮",
                  "enabled": true,
                  "priority": 1,
                  "amount_min_cents": 1000,
                  "amount_max_cents": 5000,
                  "source_contains": "pytest",
                  "tag_contains": "真香",
                  "created_at": "2026-05-13T00:00:00Z",
                  "updated_at": "2026-05-13T00:00:00Z"
                }
                """.trimIndent(),
            ),
        )

        assertEquals(1000L, dto.amountMinCents)
        assertEquals("pytest", dto.sourceContains)
        assertEquals("真香", dto.tagContains)
    }

    @Test
    fun merchantAliasListParsesCurrentServerShapeAndSerializesPatch() {
        val dto = requireNotNull(
            moshi.adapter(MerchantAliasListDto::class.java).fromJson(
                """
                {
                  "items": [
                    {
                      "public_id": "alias-1",
                      "canonical_merchant": "星巴克",
                      "canonical_key": "星巴克",
                      "alias": "Starbucks",
                      "alias_key": "starbucks",
                      "enabled": true,
                      "created_at": "2026-05-13T00:00:00Z",
                      "updated_at": "2026-05-13T00:05:00Z"
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val patchJson = moshi.adapter(MerchantAliasRequest::class.java).toJson(
            MerchantAliasRequest(enabled = false),
        )

        val item = dto.items.single()
        assertEquals("alias-1", item.publicId)
        assertEquals("星巴克", item.canonicalMerchant)
        assertEquals("starbucks", item.aliasKey)
        assertEquals("""{"enabled":false}""", patchJson)
    }

    @Test
    fun applyConfirmedRulesUsesDryRunByDefaultAndParsesPreview() {
        val requestJson = moshi.adapter(RuleApplyConfirmedRequestDto::class.java).toJson(
            RuleApplyConfirmedRequestDto(),
        )
        val dto = requireNotNull(
            moshi.adapter(RuleApplyConfirmedResponseDto::class.java).fromJson(
                """
                {
                  "dry_run": true,
                  "confirmed_scanned": 12,
                  "changed_count": 1,
                  "items": [
                    {
                      "id": 9,
                      "merchant": "高德",
                      "current_category": "其他",
                      "suggested_category": "交通",
                      "rule_keyword": "高德",
                      "reason": "merchant matched"
                    }
                  ],
                  "skipped_non_default_category": 2,
                  "no_match_count": 8,
                  "unchanged_count": 1,
                  "conflict_count": 0,
                  "scan_limit_reached": false,
                  "scan_limit": 500,
                  "preview_token": "abc123"
                }
                """.trimIndent(),
            ),
        )

        assertEquals("""{"confirm":false}""", requestJson)
        assertEquals(true, dto.dryRun)
        assertEquals("交通", dto.items.single().suggestedCategory)
        assertEquals(500, dto.scanLimit)
        assertEquals("abc123", dto.previewToken)
    }

    @Test
    fun ledgerMemberListParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(LedgerMemberListResponseDto::class.java).fromJson(
                """
                {
                  "members": [
                    {
                      "member_id": 1,
                      "account_public_id": "acc_1",
                      "account_name": "阿方",
                      "role": "owner",
                      "created_at": "2026-05-01T00:00:00Z",
                      "disabled_at": null,
                      "is_self": true
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )

        assertEquals(1L, dto.members.single().memberId)
        assertEquals("acc_1", dto.members.single().accountPublicId)
        assertEquals("阿方", dto.members.single().accountName)
        assertEquals("owner", dto.members.single().role)
        assertEquals("2026-05-01T00:00:00Z", dto.members.single().createdAt)
        assertEquals(null, dto.members.single().disabledAt)
        assertEquals(true, dto.members.single().isSelf)
    }

    @Test
    fun invitationPreviewParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(InvitationPreviewResponseDto::class.java).fromJson(
                """
                {
                  "ledger_id": "L_family",
                  "ledger_name": "家庭账本",
                  "role": "viewer",
                  "expires_at": "2026-05-20T00:00:00Z"
                }
                """.trimIndent(),
            ),
        )

        assertEquals("L_family", dto.ledgerId)
        assertEquals("家庭账本", dto.ledgerName)
        assertEquals("viewer", dto.role)
        assertEquals("2026-05-20T00:00:00Z", dto.expiresAt)
    }

    @Test
    fun ledgerAuditParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(LedgerAuditListResponseDto::class.java).fromJson(
                """
                {
                  "items": [
                    {
                      "public_id": "audit-1",
                      "ledger_id": "L_family",
                      "action": "member_role_changed",
                      "actor_account_public_id": "acc_owner",
                      "actor_account_name": "阿方",
                      "target_account_public_id": "acc_member",
                      "target_account_name": "家人",
                      "target_member_id": 2,
                      "invitation_public_id": null,
                      "previous_role": "member",
                      "new_role": "viewer",
                      "result": "success",
                      "detail": null,
                      "created_at": "2026-05-13T00:00:00Z"
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )

        val item = dto.items.single()
        assertEquals("audit-1", item.publicId)
        assertEquals("member_role_changed", item.action)
        assertEquals("阿方", item.actorAccountName)
        assertEquals("家人", item.targetAccountName)
        assertEquals(2L, item.targetMemberId)
        assertEquals("member", item.previousRole)
        assertEquals("viewer", item.newRole)
        assertEquals("success", item.result)
    }

    @Test
    fun recurringItemsParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(RecurringItemListResponseDto::class.java).fromJson(
                """
                {
                  "items": [
                    {
                      "public_id": "recurring-1",
                      "ledger_id": "owner",
                      "merchant": "ChatGPT Plus",
                      "merchant_key": "chatgpt plus",
                      "frequency": "monthly",
                      "baseline_amount_cents": 20000,
                      "last_amount_cents": 20000,
                      "occurrence_count": 3,
                      "last_seen_at": "2026-05-05T12:00:00Z",
                      "next_expected_date": "2026-06-05",
                      "status": "active",
                      "confidence": "high",
                      "source": "candidate",
                      "anomaly_status": "higher_than_average",
                      "current_month_amount_cents": 28000,
                      "historical_average_amount_cents": 20000,
                      "amount_delta_percent": 40,
                      "created_at": "2026-05-13T00:00:00Z",
                      "updated_at": "2026-05-13T00:00:00Z",
                      "paused_at": null,
                      "archived_at": null
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )

        val item = dto.items.single()
        assertEquals("recurring-1", item.publicId)
        assertEquals("owner", item.ledgerId)
        assertEquals("ChatGPT Plus", item.merchant)
        assertEquals(20000L, item.baselineAmountCents)
        assertEquals("2026-06-05", item.nextExpectedDate)
        assertEquals("active", item.status)
        assertEquals("higher_than_average", item.anomalyStatus)
        assertEquals(28000L, item.currentMonthAmountCents)
        assertEquals(40, item.amountDeltaPercent)
    }

    @Test
    fun budgetMonthlyParsesCurrentServerShapeAndSerializesUpdate() {
        val dto = requireNotNull(
            moshi.adapter(BudgetMonthlyDto::class.java).fromJson(
                """
                {
                  "ledger_id": "owner",
                  "month": "2026-05",
                  "configured": true,
                  "total_amount_cents": 500000,
                  "rollover_amount_cents": -20000,
                  "fixed_amount_cents": 98000,
                  "non_monthly_amount_cents": 30000,
                  "flex_budget_cents": 352000,
                  "spent_amount_cents": 126800,
                  "excluded_amount_cents": 45000,
                  "remaining_amount_cents": 353200,
                  "overspent_amount_cents": 0,
                  "excluded_categories": ["医疗"],
                  "excluded_breakdown": [
                    {"category": "医疗", "amount_cents": 45000, "count": 1}
                  ],
                  "category_budgets": [
                    {
                      "category": "餐饮",
                      "amount_cents": 120000,
                      "spent_amount_cents": 58000,
                      "remaining_amount_cents": 62000,
                      "overspent_amount_cents": 0
                    }
                  ],
                  "updated_at": "2026-05-13T00:00:00Z"
                }
                """.trimIndent(),
            ),
        )
        val requestJson = moshi.adapter(BudgetMonthlyUpdateRequestDto::class.java).toJson(
            BudgetMonthlyUpdateRequestDto(
                totalAmountCents = 500000,
                nonMonthlyAmountCents = 30000,
                rolloverAmountCents = -20000,
                excludedCategories = listOf("医疗"),
                categoryBudgets = listOf(BudgetCategoryRequestDto("餐饮", 120000)),
            ),
        )

        assertEquals("owner", dto.ledgerId)
        assertEquals("2026-05", dto.month)
        assertEquals(352000L, dto.flexBudgetCents)
        assertEquals(-20000L, dto.rolloverAmountCents)
        assertEquals("医疗", dto.excludedBreakdown.single().category)
        assertEquals("餐饮", dto.categoryBudgets.single().category)
        assertEquals(
            """{"total_amount_cents":500000,"non_monthly_amount_cents":30000,"rollover_amount_cents":-20000,"excluded_categories":["医疗"],"category_budgets":[{"category":"餐饮","amount_cents":120000}]}""",
            requestJson,
        )
    }

    @Test
    fun reportsOverviewParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(ReportsOverviewDto::class.java).fromJson(
                """
                {
                  "month": "2026-05",
                  "timezone": "Asia/Shanghai",
                  "granularity": "day",
                  "total_amount_cents": 4200,
                  "count": 3,
                  "previous_month": "2026-04",
                  "previous_total_amount_cents": 500,
                  "previous_count": 1,
                  "merchant_category": "餐饮",
                  "ranking_metric": "count",
                  "trend": [
                    {"bucket": "2026-05-01", "label": "05-01", "amount_cents": 1200, "count": 1}
                  ],
                  "merchant_ranking": [
                    {"merchant": "星巴克", "amount_cents": 2000, "count": 2}
                  ],
                  "category_comparison": [
                    {
                      "category": "餐饮",
                      "amount_cents": 2000,
                      "count": 2,
                      "previous_amount_cents": 500,
                      "previous_count": 1,
                      "delta_amount_cents": 1500,
                      "delta_count": 1
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )

        assertEquals("2026-05", dto.month)
        assertEquals("餐饮", dto.merchantCategory)
        assertEquals("count", dto.rankingMetric)
        assertEquals(1200L, dto.trend.single().amountCents)
        assertEquals("星巴克", dto.merchantRanking.single().merchant)
        assertEquals(1500L, dto.categoryComparison.single().deltaAmountCents)
    }

    @Test
    fun goalsParseCurrentServerShapeAndSerializeRequests() {
        val dto = requireNotNull(
            moshi.adapter(GoalListResponseDto::class.java).fromJson(
                """
                {
                  "items": [
                    {
                      "public_id": "goal-1",
                      "ledger_id": "owner",
                      "name": "本月餐饮",
                      "goal_type": "spending_limit",
                      "period": "monthly",
                      "month": "2026-05",
                      "category": "餐饮",
                      "target_amount_cents": 80000,
                      "spent_amount_cents": 64000,
                      "remaining_amount_cents": 16000,
                      "progress_percent": 80,
                      "progress_state": "near_limit",
                      "status": "active",
                      "created_at": "2026-05-13T00:00:00Z",
                      "updated_at": "2026-05-13T00:00:00Z",
                      "archived_at": null
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val createJson = moshi.adapter(GoalCreateRequestDto::class.java).toJson(
            GoalCreateRequestDto(
                name = "本月餐饮",
                month = "2026-05",
                category = "餐饮",
                targetAmountCents = 80000,
            ),
        )
        val updateJson = moshi.adapter(GoalUpdateRequestDto::class.java).toJson(
            GoalUpdateRequestDto(targetAmountCents = 90000),
        )

        val goal = dto.items.single()
        assertEquals("goal-1", goal.publicId)
        assertEquals("owner", goal.ledgerId)
        assertEquals("near_limit", goal.progressState)
        assertEquals(80, goal.progressPercent)
        assertEquals(
            """{"name":"本月餐饮","month":"2026-05","target_amount_cents":80000,"category":"餐饮","goal_type":"spending_limit","period":"monthly"}""",
            createJson,
        )
        assertEquals("""{"target_amount_cents":90000}""", updateJson)
    }

    @Test
    fun dashboardCardsParseCurrentServerShapeAndSerializeUpdate() {
        val dto = requireNotNull(
            moshi.adapter(DashboardCardsResponseDto::class.java).fromJson(
                """
                {
                  "surface": "web",
                  "items": [
                    {"key": "goals", "title": "目标", "visible": true, "position": 0},
                    {"key": "reports", "title": "报表", "visible": false, "position": 1}
                  ]
                }
                """.trimIndent(),
            ),
        )
        val requestJson = moshi.adapter(DashboardCardsUpdateRequestDto::class.java).toJson(
            DashboardCardsUpdateRequestDto(
                cards = listOf(
                    DashboardCardUpdateRequestDto("goals", visible = true, position = 0),
                    DashboardCardUpdateRequestDto("reports", visible = false, position = 1),
                ),
            ),
        )

        assertEquals("web", dto.surface)
        assertEquals("goals", dto.items.first().key)
        assertEquals(false, dto.items[1].visible)
        assertEquals(
            """{"cards":[{"key":"goals","visible":true,"position":0},{"key":"reports","visible":false,"position":1}]}""",
            requestJson,
        )
    }
}
