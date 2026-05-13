package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import kotlin.test.Test
import kotlin.test.assertEquals

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
