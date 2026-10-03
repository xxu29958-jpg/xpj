package com.ticketbox.ui.navigation

import com.google.zxing.BinaryBitmap
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import com.ticketbox.ui.components.handoffQrMatrix
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class HandoffQrTest {
    @Test
    fun renderedCodesDecodeIntoTheExistingInvitationAndBindingInputs() {
        val invitation = "https://family.example.com/web/auth/join#invite=inv_fixture_only_QR123456789"
        val decodedInvitation = decode(invitation)
        assertEquals(invitation, decodedInvitation)
        assertEquals("inv_fixture_only_QR123456789", parseFamilyInvitationLink(decodedInvitation)?.inviteToken)

        val pairing = "https://family.example.com:8443/web/auth/login#pairing=12345678"
        val decodedPairing = decode(pairing)
        assertEquals(pairing, decodedPairing)
        val input = assertNotNull(parsePairingQrLink(decodedPairing))
        assertEquals("https://family.example.com:8443", input.serverUrl)
        assertEquals("12345678", input.pairingCode)
        assertNull(parseFamilyInvitationLink(decodedPairing))
        assertNull(parsePairingQrLink(decodedInvitation))
    }

    @Test
    fun unrelatedAndMalformedQrCodesCannotBecomeEnrollmentInput() {
        listOf(
            "12345678", "https://family.example.com/other#pairing=12345678",
            "http://family.example.com/web/auth/login#pairing=12345678",
            "https://user:password@family.example.com/web/auth/login#pairing=12345678",
            "https://family.example.com/web/auth/login?pairing=12345678",
            "https://family.example.com/web/auth/login#pairing=1234567",
            "https://family.example.com/web/auth/login#pairing=12345678&next=elsewhere",
        ).forEach { assertNull(parsePairingQrLink(it)) }
    }

    private fun decode(payload: String): String {
        val matrix = handoffQrMatrix(payload)
        val pixels = IntArray(matrix.width * matrix.height) { index ->
            if (matrix[index % matrix.width, index / matrix.width]) 0xff000000.toInt() else 0xffffffff.toInt()
        }
        val image = RGBLuminanceSource(matrix.width, matrix.height, pixels)
        return QRCodeReader().decode(BinaryBitmap(HybridBinarizer(image))).text
    }
}
