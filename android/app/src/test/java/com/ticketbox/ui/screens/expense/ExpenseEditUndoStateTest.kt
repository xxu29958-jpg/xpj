package com.ticketbox.ui.screens.expense

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * 「撤销修改」affordance 的可见性：只表达「本场编辑改过、可以回到已存值」。
 * null baseline 与空串等价（初始空不是修改）；已存值未被触碰时绝不出现——
 * 当前 nullable PATCH（exclude_unset）没有清除事实的命令，不装出清除能力。
 */
internal class ExpenseEditUndoStateTest {

    @Test
    fun timeUndoHiddenWhenUntouched() {
        assertFalse(expenseEditTimeModifiedSinceBaseline("2026-05-12T10:15:00Z", "2026-05-12T10:15:00Z"))
        assertFalse(expenseEditTimeModifiedSinceBaseline("", ""))
        // baseline 为 null（服务端未存时间）与本地空串同义：不是一次修改。
        assertFalse(expenseEditTimeModifiedSinceBaseline("", null))
    }

    @Test
    fun timeUndoShownAfterLocalEdit() {
        assertTrue(expenseEditTimeModifiedSinceBaseline("2026-09-03T01:00:00Z", "2026-05-12T10:15:00Z"))
        assertTrue(expenseEditTimeModifiedSinceBaseline("2026-09-03T01:00:00Z", null))
    }

    @Test
    fun scoreUndoHiddenWhenUntouched() {
        assertFalse(expenseEditScoreModifiedSinceBaseline("3", 3))
        assertFalse(expenseEditScoreModifiedSinceBaseline("", null))
    }

    @Test
    fun scoreUndoShownAfterLocalEdit() {
        assertTrue(expenseEditScoreModifiedSinceBaseline("4", 3))
        assertTrue(expenseEditScoreModifiedSinceBaseline("2", null))
    }
}
