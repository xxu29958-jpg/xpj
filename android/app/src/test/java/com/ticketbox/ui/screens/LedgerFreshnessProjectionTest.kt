package com.ticketbox.ui.screens

import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.screens.ledger.ledgerPageMessageVisible
import com.ticketbox.viewmodel.LedgerUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * W2-B: 只读权限与数据新鲜度是正交信号。Viewer 离线也必须看见缓存/失败，
 * 不能用单一 ReadOnly tone 掩盖 freshness；权限以独立常驻行表达。
 * query 刷新成功提示与 header「已同步 HH:mm」重复，仅在 presentation 过滤；
 * manual/batch/export/error 的 command receipt 永不被过滤。
 */
class LedgerFreshnessProjectionTest {

    @Test
    fun viewerPermissionDoesNotMaskFreshnessTone() {
        assertEquals(
            DataAuthorityTone.LocalCache,
            ledgerAuthorityTone(LedgerUiState(readOnly = true)),
        )
        assertEquals(
            DataAuthorityTone.Backend,
            ledgerAuthorityTone(LedgerUiState(readOnly = true, syncedInCurrentSession = true)),
        )
    }

    @Test
    fun permissionStripFollowsReadOnlyOnly() {
        assertTrue(ledgerPermissionStripVisible(LedgerUiState(readOnly = true)))
        assertFalse(ledgerPermissionStripVisible(LedgerUiState(readOnly = false)))
    }

    @Test
    fun syncDoneReceiptIsFilteredButCommandReceiptsStay() {
        assertFalse(ledgerPageMessageVisible(UiText.res(R.string.ledger_msg_sync_done)))
        assertTrue(ledgerPageMessageVisible(UiText.res(R.string.ledger_msg_manual_saved)))
        assertTrue(ledgerPageMessageVisible(UiText.res(R.string.ledger_msg_manual_saved_offline)))
        assertFalse(ledgerPageMessageVisible(null))
    }
}
