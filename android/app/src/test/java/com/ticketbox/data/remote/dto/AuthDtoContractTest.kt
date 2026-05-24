package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class AuthDtoContractTest {
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
}
