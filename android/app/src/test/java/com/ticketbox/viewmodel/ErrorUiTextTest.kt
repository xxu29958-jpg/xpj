package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * ADR-0044 follow-up: the shared error-code → copy mapper ([Throwable.toUiText])
 * that every migrated VM error path routes through — including
 * BillSplitViewModel's accept / reject / cancel / refresh failures, which used
 * `err.message?.let(UiText::raw)` (bypassing the code map) until this round.
 *
 * BillSplitViewModel's repo deps are final classes (no TagActions-style
 * interface to fake), so the mapping is pinned here at the real seam the VM
 * calls — not via a faked VM.
 */
class ErrorUiTextTest {

    @Test
    fun knownCodeMapsToResourceNotRawServerMessage() {
        // A known backend code resolves to its R.string.error_*, NOT the raw
        // server message — that is the regression the BillSplit fix restores.
        val ex = RepositoryException("服务端原始消息（不该直接展示）", "server_error")
        assertEquals(UiText.res(R.string.error_server_error), ex.toUiText(R.string.error_generic))
    }

    @Test
    fun permissionDeniedMapsToReadOnlyCopy() {
        val ex = RepositoryException("ignored raw", "permission_denied")
        assertEquals(UiText.res(R.string.error_permission_denied), ex.toUiText(R.string.error_generic))
    }

    @Test
    fun unmappedCodeKeepsResolvedServerMessageAsRaw() {
        // A code with no entry in errorCodeStringRes falls back to the server's
        // resolved message (preserves each screen's prior raw-message behavior).
        val ex = RepositoryException("这条拆账邀请已被处理。", "bill_split_already_resolved")
        assertEquals(UiText.raw("这条拆账邀请已被处理。"), ex.toUiText(R.string.error_generic))
    }

    @Test
    fun noCodeNoMessageUsesScreenFallback() {
        assertEquals(
            UiText.res(R.string.error_generic),
            RepositoryException("").toUiText(R.string.error_generic),
        )
    }

    @Test
    fun plainThrowableUsesMessageThenFallback() {
        assertEquals(UiText.raw("boom"), RuntimeException("boom").toUiText(R.string.error_generic))
        assertEquals(
            UiText.res(R.string.error_generic),
            RuntimeException().toUiText(R.string.error_generic),
        )
    }
}
