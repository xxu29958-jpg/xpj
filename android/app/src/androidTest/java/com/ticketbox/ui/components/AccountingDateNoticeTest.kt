package com.ticketbox.ui.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.Assert.assertEquals

@RunWith(AndroidJUnit4::class)
class AccountingDateNoticeTest {
    @get:Rule val compose = createComposeRule()

    @Test fun unknownDateNoticeKeepsTheRealReviewActionAvailable() {
        var opened = 0
        compose.setContent {
            MaterialTheme {
                CompositionLocalProvider(LocalAccountingDateReview provides { opened += 1 }) {
                    AccountingDateNotice(2)
                }
            }
        }
        compose.onNodeWithText("有 2 笔账单的账务日期待核对；涉及这些账单的期间金额和进度暂不可评估。").assertExists()
        compose.onNodeWithTag("review-accounting-dates").performClick()
        compose.runOnIdle { assertEquals(1, opened) }
    }
}
