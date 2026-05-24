package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class CategoryRuleDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

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
}
