package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class LedgerDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

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
}
