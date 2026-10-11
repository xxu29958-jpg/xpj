package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.repository.toDomain
import kotlin.test.Test
import kotlin.test.assertEquals

class CategoryRuleDtoContractTest {
    private val moshi = Moshi.Builder()
        .addCategoryRuleWireAdapters()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun newDefinitionClearsTextConditionsWithoutChangingTheOriginalLegacyReplayBody() {
        val request = CategoryRuleRequest("早餐", "餐饮", true, 10)
        val legacy = com.ticketbox.data.repository.CategoryRuleSubmissionPayload(expectedRowVersion = 7, request = request)
        val adapter = moshi.adapter(CategoryRuleUpdateRequest::class.java)
        assertEquals("""{"expected_row_version":7,"keyword":"早餐","category":"餐饮","enabled":true,"priority":10}""",
            adapter.toJson(legacy.updateRequest()))
        val current = legacy.copy(version = 2, originalInput = mapOf("source_contains" to "", "tag_contains" to ""))
        val wire = requireNotNull(moshi.adapter(Map::class.java).fromJson(adapter.toJson(current.updateRequest())))
        assertEquals("", wire["source_contains"], "An absent field leaves the old condition in place")
        assertEquals("", wire["tag_contains"], "An absent field leaves the old condition in place")
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
                      "status": "rollback_partial",
                      "pending_scanned": 20,
                      "changed_count": 3,
                      "created_at": "2026-05-13T00:00:00Z",
                      "rolled_back_at": "2026-05-14T00:00:00Z",
                      "change_counts": {"rolled_back": 2, "skipped": 1}
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
        assertEquals(mapOf("rolled_back" to 2, "skipped" to 1), item.toDomain().changeCounts)
        val legacy = requireNotNull(moshi.adapter(RuleApplicationBatchDto::class.java).fromJson(
            """{"public_id":"old","status":"rolled_back","pending_scanned":3,"changed_count":3,"created_at":"2026-05-13T00:00:00Z"}"""))
        assertEquals(null, legacy.toDomain().changeCounts, "An old response must not invent zero outcomes")
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
                  "home_currency_code": "JPY",
                  "amount_max_cents": 5000,
                  "source_contains": "pytest",
                  "tag_contains": "真香",
                  "created_at": "2026-05-13T00:00:00Z",
                  "updated_at": "2026-05-13T00:00:00Z",
                  "row_version": 1
                }
                """.trimIndent(),
            ),
        )

        assertEquals(1000L, dto.amountMinCents)
        assertEquals("JPY", dto.homeCurrencyCode)
        assertEquals("pytest", dto.sourceContains)
        assertEquals("真香", dto.tagContains)
    }

    @Test
    fun categoryRuleUpdateAndDeleteCarryExpectedUpdatedAt() {
        // ADR-0038 PR-1: PATCH/DELETE bodies must carry expected_row_version
        // (and DELETE actually sends a body now).
        val updateJson = moshi.adapter(CategoryRuleUpdateRequest::class.java).toJson(
            CategoryRuleUpdateRequest(
                expectedRowVersion = 1L,
                enabled = false,
            ),
        )
        val deleteJson = moshi.adapter(CategoryRuleDeleteRequest::class.java).toJson(
            CategoryRuleDeleteRequest(expectedRowVersion = 1L),
        )
        assertEquals(
            """{"expected_row_version":1,"enabled":false}""",
            updateJson,
        )
        assertEquals(
            """{"expected_row_version":1}""",
            deleteJson,
        )
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
                  "preview_token": "abc123",
                  "unavailable_count": 2,
                  "missing_currency_codes": ["JPY"]
                }
                """.trimIndent(),
            ),
        )

        assertEquals("""{"confirm":false}""", requestJson)
        assertEquals(true, dto.dryRun)
        assertEquals("交通", dto.items.single().suggestedCategory)
        assertEquals(500, dto.scanLimit)
        assertEquals("abc123", dto.previewToken)
        assertEquals(2, dto.unavailableCount)
        assertEquals(listOf("JPY"), dto.missingCurrencyCodes)
    }
}
