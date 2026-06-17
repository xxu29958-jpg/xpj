package com.ticketbox.ui.screens

import com.ticketbox.R
import com.ticketbox.domain.model.RepaymentDraftSource
import kotlin.test.Test
import kotlin.test.assertEquals

class RepaymentDraftLabelsTest {
    @Test
    fun mapsEveryKnownSourceToItsLabel() {
        assertEquals(R.string.repayment_draft_source_alipay, repaymentDraftSourceLabelRes(RepaymentDraftSource.Alipay.apiValue))
        assertEquals(R.string.repayment_draft_source_jd, repaymentDraftSourceLabelRes(RepaymentDraftSource.Jd.apiValue))
        assertEquals(R.string.repayment_draft_source_meituan, repaymentDraftSourceLabelRes(RepaymentDraftSource.Meituan.apiValue))
        assertEquals(R.string.repayment_draft_source_wechat, repaymentDraftSourceLabelRes(RepaymentDraftSource.WeChat.apiValue))
        assertEquals(R.string.repayment_draft_source_bank_sms, repaymentDraftSourceLabelRes(RepaymentDraftSource.BankSms.apiValue))
        assertEquals(R.string.repayment_draft_source_bank_app, repaymentDraftSourceLabelRes(RepaymentDraftSource.BankApp.apiValue))
        assertEquals(R.string.repayment_draft_source_other, repaymentDraftSourceLabelRes(RepaymentDraftSource.Other.apiValue))
    }

    @Test
    fun unknownSourceFallsBackToOther() {
        // 前向兼容:后端将来新增渠道时,客户端不崩、回落「其他还款」。
        assertEquals(R.string.repayment_draft_source_other, repaymentDraftSourceLabelRes("brand_new_channel"))
    }
}
